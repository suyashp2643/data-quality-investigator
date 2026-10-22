"""Local HTTP protocol tests: these are NOT evidence of real model performance."""
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from dqagent.eval_runtime import Chat, summarize


def test_http_usage_and_invalid_json():
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            content = '{"findings": []}' if len(requests) == 1 else 'not-json'
            body = json.dumps({"model": "protocol-test-only", "usage": {"total_tokens": 12},
                "choices": [{"message": {"content": content}}]}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        chat = Chat("protocol-test", endpoint=f"http://127.0.0.1:{server.server_port}/v1", key="fake-test-key")
        assert chat.ask([{"role": "user", "content": "test"}]) == {"findings": []}
        assert chat.calls[0]["usage"]["total_tokens"] == 12
        with pytest.raises(json.JSONDecodeError):
            chat.ask([{"role": "user", "content": "test"}])
        assert len(chat.calls) == 2
        assert requests[0]["max_tokens"] == 1600
        assert requests[0]["model"] == "protocol-test"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_errors_stay_in_denominator_and_pairing():
    rows = [
        {"case": "x", "repeat": 0, "method": "single_shot", "success": True, "seconds": 1},
        {"case": "x", "repeat": 0, "method": "agent", "status": "error", "seconds": 2},
        {"case": "y", "repeat": 0, "method": "agent", "success": True, "seconds": 3},
        {"case": "y", "repeat": 0, "method": "single_shot", "success": False, "seconds": 1}]
    summary = summarize(rows)
    assert summary["methods"]["agent"]["success_rate"] == 0.5
    assert summary["methods"]["agent"]["errors"] == 1
    assert summary["paired"] == [{"baseline": "single_shot", "pairs": 2, "agent_only_success": 1, "baseline_only_success": 1}]

from dqagent.evaluate import make_cases, score, solve


def test_mixed_fault_oracle_and_rules_baseline():
    cases = make_cases(19, 32)
    assert cases == make_cases(19, 32)
    assert cases != make_cases(20, 32)
    assert {c["mask"] for c in cases} == set(range(16))
    for case in cases:
        result = solve(case, "rules", None)
        assert result["success"], result
        assert result["unchanged"]
        assert result["calls"] == []
        assert result["tool_calls"] == 5


def test_missing_invented_and_duplicate_citations_fail():
    expected = {"duplicate_orders"}
    assert not score([{ "code": "duplicate_orders", "evidence": "duplicates"}], expected, {})["success"]
    assert not score([{ "code": "missing_amounts", "evidence": "null_amounts"}], expected, {"null_amounts": []})["success"]
    finding = {"code": "duplicate_orders", "evidence": "duplicates"}
    assert not score([finding, finding], expected, {"duplicates": []})["success"]
    assert score([finding], expected, {"duplicates": [{"order_id": "x", "copies": 2}]})["success"]


def test_cli_records_failed_model_workers_in_complete_report(tmp_path):
    import os
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"choices":[{"message":{"content":"invalid-json"}}]}')
        def log_message(self, *_):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        output = tmp_path / "protocol-only.json"
        env = dict(os.environ, LLM_API_KEY="fake-protocol-secret", LLM_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1")
        process = subprocess.run([sys.executable, "-m", "dqagent.evaluate", "--model", "protocol-test", "--limit", "1", "--output", str(output)], env=env, capture_output=True, text=True, timeout=30)
        assert process.returncode != 0
        report = json.loads(output.read_text())
        assert report["complete"] and len(report["results"]) == 3
        assert report["summary"]["methods"]["rules"]["successes"] == 1
        assert report["summary"]["methods"]["agent"]["errors"] == 1
        assert report["summary"]["methods"]["single_shot"]["errors"] == 1
        assert "fake-protocol-secret" not in output.read_text()
        assert output.with_suffix(".html").exists()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_adaptive_tool_loop_with_real_local_http_boundary():
    from dqagent.evaluate import make_cases, solve
    case = next(c for c in make_cases(43, 16) if c["mask"] == 3)
    requests = []
    replies = [{"tool": tool} for tool in ["duplicates", "null_amounts", "freshness", "volume"]]
    replies.append({"findings": [{"code": "duplicate_orders", "evidence": "duplicates"}, {"code": "missing_amounts", "evidence": "null_amounts"}]})
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = {"model": "protocol-test", "choices": [{"message": {"content": json.dumps(replies[len(requests)-1])}}]}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())
        def log_message(self, *_):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = solve(case, "agent", Chat("protocol-test", f"http://127.0.0.1:{server.server_port}/v1", "fake-key"))
        assert result["success"] and result["unchanged"]
        assert result["tool_calls"] == 4 and len(result["calls"]) == 5
        assert "revenue" not in {row["tool"] for row in result["trace"]}
        assert all('"mask"' not in json.dumps(request) and '"seed"' not in json.dumps(request) for request in requests)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
