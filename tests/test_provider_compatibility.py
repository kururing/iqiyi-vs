"""Check catalog and chat HTTP requests share the app's client identity."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from translation_ai import list_models, model_config, request_json


class ProviderCompatibilityTest(unittest.TestCase):
    def test_catalog_and_chat_send_app_user_agent(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def respond(self, data):
                raw = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                requests.append((self.path, dict(self.headers)))
                self.respond({"data": [{"id": "test-model"}]})

            def do_POST(self):
                requests.append((self.path, dict(self.headers)))
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert data["model"] == "test-model"
                self.respond({"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]})

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        config = model_config({"provider": "custom", "base_url": f"http://127.0.0.1:{server.server_port}/v1/",
                               "api_key": "local-test-key", "model": "test-model"})
        self.assertEqual(list_models(config), [{"id": "test-model", "name": "test-model"}])
        self.assertEqual(request_json(config, "Return JSON.", {}, threading.Event()), {"ok": True})
        self.assertEqual([route for route, _ in requests], ["/v1/models", "/v1/chat/completions"])
        for _, headers in requests:
            with self.subTest(headers=headers):
                normalized = {key.lower(): value for key, value in headers.items()}
                self.assertEqual(normalized["user-agent"], "IQIYI-VI/1.0")
                self.assertEqual(normalized["authorization"], "Bearer local-test-key")


if __name__ == "__main__":
    unittest.main()
