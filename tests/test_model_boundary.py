import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from dqagent.core import LLMPlanner


def test_real_http_model_response_is_validated(monkeypatch):
    replies = ["volume", "DROP TABLE orders"]
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"choices": [{"message": {"content": json.dumps({"tool": replies.pop(0)})}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("LLM_API_KEY", "local-test-only")
    try:
        planner = LLMPlanner("test-model")
        assert planner.next_tool("check", {}, ["volume"]) == "volume"
        with pytest.raises(ValueError, match="unavailable tool"):
            planner.next_tool("check", {}, ["volume"])
        assert requests[0]["max_tokens"] == 100
        assert requests[0]["model"] == "test-model"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
