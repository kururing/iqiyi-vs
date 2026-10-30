"""A loopback HTTP/CONNECT relay for desktop proxy authentication."""
import base64
import ipaddress
import select
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

IQIYI_PROXY_DOMAINS = ("iqiyi.com", "qiyi.com", "qiyipic.com", "iqiyipic.com", "iqiyicloud.com", "qy.net")


def is_iqiyi_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in IQIYI_PROXY_DOMAINS)


def proxy_authorization(proxy) -> str:
    if proxy.username is None:
        return ""
    credentials = unquote(proxy.username) + ":" + unquote(proxy.password or "")
    return "Basic " + base64.b64encode(credentials.encode()).decode("ascii")


def is_loopback(host: str) -> bool:
    if host.lower().rstrip(".") == "localhost" or host.lower().rstrip(".").endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def connect_tunnel(upstream, authority: str, authorization: str = ""):
    headers = f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n"
    if authorization:
        headers += "Proxy-Authorization: " + authorization + "\r\n"
    upstream.sendall((headers + "\r\n").encode("latin-1"))
    # Unbuffered reads leave any tunnel bytes on the socket for the relay.
    with upstream.makefile("rb", buffering=0) as response:
        status_line = response.readline(65537)
        status = status_line.split()
        size = len(status_line)
        if len(status) < 2 or not status[0].startswith(b"HTTP/") or not status[1].isdigit():
            raise OSError("Proxy trả phản hồi không hợp lệ.")
        while True:
            line = response.readline(65537)
            size += len(line)
            if size > 65536 or not line:
                raise OSError("Proxy trả phản hồi không hợp lệ.")
            if line == b"\r\n":
                break
    code = int(status[1])
    if code == 407:
        raise OSError("Proxy từ chối xác thực (HTTP 407). Kiểm tra tài khoản, mật khẩu hoặc IP được phép dùng proxy.")
    if code == 403:
        raise OSError("Proxy từ chối truy cập iQIYI (HTTP 403). Kiểm tra quyền truy cập và IP được phép tại nhà cung cấp proxy.")
    if not 200 <= code < 300:
        raise OSError(f"Proxy không mở được kết nối tới iQIYI (HTTP {code}). Kiểm tra trạng thái proxy tại nhà cung cấp.")


def check_iqiyi_proxy(proxy_url: str):
    """Verify credentials and a real TLS tunnel before changing the active proxy."""
    proxy = urlsplit(proxy_url)
    try:
        upstream = socket.create_connection((proxy.hostname, proxy.port), timeout=10)
    except socket.gaierror:
        raise OSError("Không tìm thấy máy chủ proxy. Kiểm tra lại địa chỉ máy chủ.") from None
    except OSError:
        raise OSError("Không kết nối được máy chủ proxy. Kiểm tra địa chỉ, cổng và trạng thái proxy.") from None
    with upstream:
        try:
            connect_tunnel(upstream, "www.iqiyi.com:443", proxy_authorization(proxy))
        except (TimeoutError, ConnectionError):
            raise OSError("Proxy không phản hồi hoặc đã ngắt kết nối. Kiểm tra trạng thái proxy rồi thử lại.") from None
        try:
            with ssl.create_default_context().wrap_socket(upstream, server_hostname="www.iqiyi.com"):
                pass
        except OSError:
            raise OSError("Proxy đã nhận kết nối nhưng không thiết lập được HTTPS tới iQIYI. Kiểm tra proxy hoặc thử lại.") from None


class _DesktopProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    rbufsize = 0  # Leave request bodies on the socket for the bidirectional relay.

    def log_message(self, *_):
        pass

    def _forward(self, tunnel=False):
        upstream = None
        forwarding = False
        try:
            target = urlsplit("http://" + self.path if tunnel else self.path)
            port = target.port or (443 if tunnel else 80)
            if (target.scheme != "http" or not target.hostname or target.username is not None or
                    target.fragment or (tunnel and (target.path or target.query))):
                self.send_error(400, "Invalid proxy target")
                return
            proxy_url = self.server.proxy_url()
            # Match the browser PAC: metadata needs the proxy, external video CDNs
            # go direct. Sending 71edge.com through public proxies stalls native playback.
            proxy = urlsplit(proxy_url) if proxy_url and is_iqiyi_host(target.hostname) else None
            upstream = socket.create_connection(
                (proxy.hostname, proxy.port) if proxy else (target.hostname, port), timeout=15)
            authorization = proxy_authorization(proxy) if proxy else ""
            if tunnel and proxy:
                connect_tunnel(upstream, self.path, authorization)
            if tunnel:
                self.send_response_only(200, "Connection Established")
                self.end_headers()
            else:
                path = self.path if proxy else (target.path or "/") + ("?" + target.query if target.query else "")
                headers = f"{self.command} {path} HTTP/1.1\r\n"
                headers += "".join(f"{key}: {value}\r\n" for key, value in self.headers.items()
                                   if key.lower() not in ("proxy-authorization", "proxy-connection", "connection"))
                if authorization:
                    headers += "Proxy-Authorization: " + authorization + "\r\n"
                upstream.sendall((headers + "Connection: close\r\n\r\n").encode("latin-1"))
            forwarding = True
            self.close_connection = True
            self.connection.settimeout(30)
            peers = {self.connection: upstream, upstream: self.connection}
            readers = list(peers)
            while readers:
                ready, _, _ = select.select(readers, [], [], 120)
                if not ready:
                    break
                for source in ready:
                    data = source.recv(65536)
                    if data:
                        peers[source].sendall(data)
                    else:
                        readers.remove(source)
                        peers[source].shutdown(socket.SHUT_WR)
        except (OSError, ValueError):
            if not forwarding:
                try:
                    self.send_error(502, "Proxy connection failed")
                except OSError:
                    pass  # The player may have already cancelled this request.
            self.close_connection = True
        finally:
            if upstream is not None:
                upstream.close()

    def do_CONNECT(self):
        self._forward(tunnel=True)

    def do_GET(self):
        self._forward()

    do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = do_GET


class DesktopProxyRelay:
    def __init__(self, proxy_url):
        self.proxy_url = proxy_url
        self.lock = threading.Lock()
        self.server = None

    def url(self) -> str:
        with self.lock:
            if self.server is None:
                self.server = ThreadingHTTPServer(("127.0.0.1", 0), _DesktopProxyHandler)
                self.server.proxy_url = self.proxy_url
                threading.Thread(target=self.server.serve_forever, daemon=True, name="desktop-proxy").start()
            return f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        with self.lock:
            if self.server is not None:
                self.server.shutdown()
                self.server.server_close()
                self.server = None
