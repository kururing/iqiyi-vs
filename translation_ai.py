"""Provider configuration and bounded JSON requests; no credentials are persisted."""
from __future__ import annotations

import json
import http.client
import io
import re
import math
import socket
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit
from email.utils import parsedate_to_datetime
from iqcom_requests import read_response

PRESETS = [
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "protocol": "openai"},
    {"id": "anthropic", "name": "Anthropic / Claude", "base_url": "https://api.anthropic.com/v1", "protocol": "anthropic"},
    {"id": "gemini", "name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "protocol": "openai"},
    {"id": "qwen", "name": "Qwen / DashScope (Singapore)", "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "protocol": "openai"},
    {"id": "custom", "name": "Tùy chỉnh (OpenAI compatible)", "base_url": "", "protocol": "openai"},
]
MODEL_MAX_TOKENS = 8192


class ProviderError(ValueError):
    pass


class RateLimitError(ProviderError):
    def __init__(self, retry_after: float):
        self.retry_after = max(0, retry_after)
        super().__init__("Provider giới hạn yêu cầu hoặc đã hết hạn mức (HTTP 429). "
                         f"Thử Dịch tiếp sau ít nhất {math.ceil(self.retry_after)} giây; "
                         "nếu vẫn lỗi, kiểm tra hạn mức của tài khoản provider.")


def retry_delay(header: str, body: bytes, fallback: float) -> float:
    delay = fallback
    if re.fullmatch(r"\d+(?:\.\d+)?", header.strip()):
        delay = float(header)
    elif header:
        try:
            delay = max(0, parsedate_to_datetime(header).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            pass
    try:
        error = json.loads(body).get("error", {})
        for detail in error.get("details", []):
            if detail.get("@type", "").endswith("google.rpc.RetryInfo"):
                match = re.fullmatch(r"(\d+(?:\.\d+)?)s", detail.get("retryDelay", ""))
                if match:
                    delay = max(delay, float(match[1]))
    except (ValueError, TypeError, AttributeError):
        pass
    return delay if math.isfinite(delay) else fallback


class RateLimitGate:
    """Share provider cooldown across batches; space retries after the first 429."""
    def __init__(self):
        self.lock = threading.Lock()
        self.until = 0
        self.spacing = 0

    def defer(self, delay):
        with self.lock:
            self.until = max(self.until, time.monotonic() + delay)
            self.spacing = 3

    def wait(self, cancel):
        while not cancel.is_set():
            with self.lock:
                delay = self.until - time.monotonic()
                if delay <= 0:
                    self.until = time.monotonic() + self.spacing
                    return
            cancel.wait(min(delay, 1))
        raise Cancelled("Đã hủy dịch.")


class Cancelled(ValueError):
    pass


def model_config(value: object, *, require_model: bool = True) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Thiếu cấu hình model.")
    preset = next((p for p in PRESETS if p["id"] == value.get("provider")), None)
    if not preset:
        raise ValueError("Provider không hợp lệ.")
    result = {"provider": preset["id"], "protocol": preset["protocol"]}
    for key, maximum in (("base_url", 2048), ("api_key", 4096), ("model", 200), ("workspace_id", 200)):
        item = value.get(key, preset.get(key, ""))
        if not isinstance(item, str) or len(item) > maximum or re.search(r"[\x00-\x1f\x7f]", item):
            raise ValueError(f"Cấu hình {key} không hợp lệ.")
        result[key] = item.strip()
    result["base_url"] = result["base_url"].rstrip("/")
    url = urlsplit(result["base_url"])
    try:
        url.port
    except ValueError:
        raise ValueError("Cổng API không hợp lệ.") from None
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or not (url.scheme == "https" or (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")))):
        raise ValueError("Base URL phải dùng HTTPS (HTTP chỉ dành cho localhost), không chứa khóa hay query.")
    if require_model and not result["model"]:
        raise ValueError("Chọn hoặc nhập tên model của provider.")
    if not result["api_key"] and url.scheme != "http":
        raise ValueError("Nhập API key của provider.")
    result["max_tokens"] = MODEL_MAX_TOKENS
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward API credentials to a redirected host.
        return None


def provider_headers(config: dict) -> dict:
    headers = {"Content-Type": "application/json", "User-Agent": "IQIYI-VI/1.0"}
    if config["protocol"] == "anthropic":
        headers.update({"x-api-key": config["api_key"], "anthropic-version": "2023-06-01"})
        if config["workspace_id"]:
            headers["anthropic-workspace-id"] = config["workspace_id"]
    elif config["api_key"]:
        headers["Authorization"] = "Bearer " + config["api_key"]
    return headers


def list_models(value: object) -> list[dict]:
    """Read provider catalog server-side; never expose keys or provider error bodies."""
    config = model_config(value, require_model=False)
    headers = provider_headers(config)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    models, cursors, cursor = {}, set(), ""
    deadline = time.monotonic() + 45
    for _ in range(10):
        query = {"limit": 1000} if config["protocol"] == "anthropic" else {}
        if cursor:
            query["after_id" if config["protocol"] == "anthropic" else "after"] = cursor
        url = config["base_url"] + "/models" + ("?" + urlencode(query) if query else "")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderError("Quét model quá thời gian chờ. Hãy thử lại.")
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=min(15, remaining)) as response:
                raw = read_response(response, 2_000_000)
            if len(raw) > 2_000_000:
                raise ValueError
            data = json.loads(raw)
            rows = data.get("data")
            if not isinstance(rows, list):
                raise ValueError
            for row in rows:
                model_id = row.get("id") if isinstance(row, dict) else None
                if not isinstance(model_id, str) or not 1 <= len(model_id) <= 200 or re.search(r"[\x00-\x20\x7f]", model_id):
                    raise ValueError
                label = row.get("display_name") or model_id
                models[model_id] = {"id": model_id, "name": label[:200] if isinstance(label, str) else model_id}
            if len(models) > 10000:
                raise ValueError
            if not data.get("has_more"):
                return sorted(models.values(), key=lambda item: item["id"].casefold())
            cursor = data.get("last_id") or (rows[-1]["id"] if rows else "")
            if not isinstance(cursor, str) or not cursor or cursor in cursors or cursor not in models:
                raise ValueError
            cursors.add(cursor)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            hint = "Provider không hỗ trợ danh sách model tại URL này. Kiểm tra Base URL và quét lại." if code in (404, 405) else "Kiểm tra API key, Base URL, workspace và hạn mức rồi quét lại."
            raise ProviderError(f"Quét model thất bại (HTTP {code}). {hint}") from None
        except OSError:
            raise ProviderError("Không kết nối được provider hoặc hết thời gian chờ. Kiểm tra Base URL và thử lại.") from None
        except (ValueError, TypeError, AttributeError, KeyError):
            raise ProviderError("Provider trả danh sách model không hợp lệ. Kiểm tra Base URL và quét lại.") from None
    raise ProviderError("Danh sách model có quá nhiều trang. Hãy kiểm tra Base URL của provider.")


def read_api_response(request, cancel):
    """Interrupt an in-flight request, including waiting for headers or body."""
    url = urlsplit(request.full_url)
    connection_type = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    connection = connection_type(url.hostname, url.port, timeout=120)
    done = threading.Event()
    result, errors, sockets = [], [], []

    def read():
        try:
            connection.connect()
            # DNS/connect may finish after cancellation. Never send that request.
            if cancel.is_set():
                raise Cancelled("Đã hủy dịch.")
            sockets.append(connection.sock)
            connection.request("POST", url.path or "/", body=request.data,
                               headers={name.title(): value for name, value in request.header_items()})
            with connection.getresponse() as response:
                raw = (read_response(response, 2_000_000) if response.status < 300 else
                       response.read(16000) if response.status == 429 else b"")
                if response.status >= 300:
                    raise urllib.error.HTTPError(request.full_url, response.status, response.reason,
                                                 response.headers, io.BytesIO(raw))
                result.append(raw)
        except Exception as exc:
            errors.append(exc)
        finally:
            connection.close()
            done.set()

    threading.Thread(target=read, name="translation-http", daemon=True).start()
    while not done.wait(.05):
        if cancel.is_set():
            break
    if cancel.is_set():
        # shutdown wakes a blocked read; close alone can wait for that read on Windows.
        for sock in [connection.sock, *sockets]:
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        raise Cancelled("Đã hủy dịch.")
    if errors:
        if isinstance(errors[0], http.client.HTTPException):
            raise OSError("API connection failed") from None
        raise errors[0]
    return result[0]


def request_json(config: dict, system: str, payload: dict, cancel) -> object:
    if cancel.is_set():
        raise Cancelled("Đã hủy dịch.")
    headers = provider_headers(config)
    user = json.dumps(payload, ensure_ascii=False)
    body = {"model": config["model"], "messages": [{"role": "user", "content": user}]}
    if config["protocol"] == "anthropic":
        endpoint = "/messages"
        body.update(system=system, max_tokens=config["max_tokens"])
    else:
        endpoint = "/chat/completions"
        body["messages"].insert(0, {"role": "system", "content": system})
        token_key = "max_completion_tokens" if config["provider"] == "openai" else "max_tokens"
        body[token_key] = config["max_tokens"]
        if config.get("_reasoning_effort"):
            body["reasoning_effort"] = config["_reasoning_effort"]
    request = urllib.request.Request(config["base_url"] + endpoint,
                                     json.dumps(body, ensure_ascii=False).encode("utf-8"), headers)
    for attempt in range(3):
        if cancel.is_set():
            raise Cancelled("Đã hủy dịch.")
        gate = config.get("_rate_gate")
        if gate:
            gate.wait(cancel)
        try:
            raw = read_api_response(request, cancel)
            if len(raw) > 2_000_000:
                raise ProviderError("Phản hồi API quá lớn.")
            data = json.loads(raw)
            if config["protocol"] == "anthropic":
                if data.get("stop_reason") != "end_turn":
                    raise ValueError("Model chưa hoàn tất JSON; kiểm tra giới hạn token đầu ra.")
                content = "".join(part["text"] for part in data["content"] if part.get("type") == "text")
            else:
                choice = data["choices"][0]
                if choice.get("finish_reason") != "stop":
                    raise ValueError("Model chưa hoàn tất JSON; kiểm tra giới hạn token đầu ra.")
                content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Model không trả văn bản JSON.")
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
            return json.loads(content)
        except urllib.error.HTTPError as exc:
            code = exc.code
            retry_after = exc.headers.get("Retry-After", "")
            error_body = exc.read(16000) if code == 429 else b""
            exc.close()
            if code == 429:
                delay = retry_delay(retry_after, error_body, 15 * 2 ** attempt)
                if gate:
                    gate.defer(delay)
                if attempt == 2 or delay > 60:
                    raise RateLimitError(delay) from None
                if config.get("_on_retry"):
                    config["_on_retry"](delay)
                if cancel.wait(delay):
                    raise Cancelled("Đã hủy dịch.")
                continue
            if code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                raise ProviderError(f"API trả HTTP {code}. Kiểm tra URL, API key, quyền model và hạn mức.") from None
            delay = min(30, int(retry_after)) if retry_after.isdigit() else 2 ** (attempt + 1)
        except OSError:
            if attempt == 2:
                raise ProviderError("Không kết nối được API hoặc quá thời gian chờ. Kiểm tra mạng và Base URL.") from None
            delay = 2 ** (attempt + 1)
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ValueError("Phản hồi không đúng định dạng API đã chọn.") from None
        except json.JSONDecodeError:
            raise ValueError("Model trả JSON không hợp lệ.") from None
        except UnicodeError:
            raise ValueError("API trả dữ liệu UTF-8 bị thiếu hoặc không hợp lệ; hãy thử lại.") from None
        if cancel.wait(delay):
            raise Cancelled("Đã hủy dịch.")
