"""A loopback HTTP/CONNECT relay for desktop proxy authentication."""
import base64
import ipaddress
import select
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit


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
            proxy = urlsplit(proxy_url) if proxy_url and not is_loopback(target.hostname) else None
            upstream = socket.create_connection(
                (proxy.hostname, proxy.port) if proxy else (target.hostname, port), timeout=15)
            authorization = proxy_authorization(proxy) if proxy else ""
            if tunnel and proxy:
                headers = f"CONNECT {self.path} HTTP/1.1\r\nHost: {self.path}\r\n"
                if authorization:
                    headers += "Proxy-Authorization: " + authorization + "\r\n"
                upstream.sendall((headers + "\r\n").encode("latin-1"))
                with upstream.makefile("rb", buffering=0) as response:
                    status = response.readline(65537)
                    size = len(status)
                    while True:
                        line = response.readline(65537)
                        size += len(line)
                        if size > 65536 or not line:
                            raise OSError("Invalid upstream response")
                        if line == b"\r\n":
                            break
                if status.split()[1:2] != [b"200"]:
                    self.send_error(502, "Upstream proxy refused tunnel")
                    return
            if tunnel:
                self.send_response(200, "Connection Established")
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
                self.send_error(502, "Proxy connection failed")
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
