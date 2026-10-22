"""Local HTTP protocol tests: these are NOT evidence of real model performance."""
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from dqagent.eval_runtime import Chat, summarize


def test_http_usage_and_invalid_json(tmp_path):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.headers.get("User-Agent") != "agent-evaluation/1.0":
                self.send_response(403)
                self.end_headers()
                return
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
        chat = Chat("protocol-test", endpoint=f"http://127.0.0.1:{server.server_port}/v1", key="fake-test-key", json_mode=True, trace_path=tmp_path / "calls.json")
        assert chat.ask([{"role": "user", "content": "test"}]) == {"findings": []}
        assert chat.calls[0]["usage"]["total_tokens"] == 12
        with pytest.raises(json.JSONDecodeError):
            chat.ask([{"role": "user", "content": "test"}])
        assert len(chat.calls) == 2
        saved = json.loads((tmp_path / "calls.json").read_text())
        assert len(saved) == 2 and saved[1]["response"] == "not-json"
        assert requests[0]["response_format"] == {"type": "json_object"}
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
            self.wfile.write(b'{"choices":[{"message":{"content":"invalid-json"},"finish_reason":"length"}],"usage":{"total_tokens":12}}')
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
        failed = [row for row in report["results"] if row["status"] == "error"]
        assert all(len(row["calls"]) == 1 and row["error"]["category"] == "model_output_truncated" for row in failed)
        assert all(row["calls"][0]["usage"]["total_tokens"] == 12 for row in failed)
        assert report["configuration"]["response_format"] == {"type": "json_object"}
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


def test_worker_diagnostics_redact_provider_details():
    from dqagent.eval_runtime import worker_error
    assert worker_error("urllib.error.HTTPError: HTTP Error 401: do-not-expose-test-key", 1) == {
        "returncode": 1, "http_status": 401, "category": "provider_authentication_failed"}
    assert worker_error("HTTP Error 429: account private detail", 1)["category"] == "provider_rate_limit_or_quota"
    assert worker_error("json.decoder.JSONDecodeError: private response", 1)["category"] == "model_returned_invalid_json"
    assert worker_error("private unknown exception", 124)["category"] == "worker_timeout"
    assert "private" not in str(worker_error("private unknown exception", 1))


def test_ansi_and_unexpected_response_diagnostics():
    from dqagent.eval_runtime import worker_error
    assert worker_error("\x1b[31mHTTPError: HTTP Error 403: Forbidden\x1b[0m", 1)["http_status"] == 403
    result = worker_error("TypeError: secret-provider-response-must-not-leak", 1)
    assert result["exception_type"] == "TypeError"
    assert result["category"] == "unexpected_response_type"
    assert "secret-provider" not in str(result)
    assert worker_error("Usage: python -m portfolio.evaluate [OPTIONS]", 2)["category"] == "worker_cli_arguments_rejected"


@pytest.mark.parametrize(("behavior",), [("recover",), ("keep_stopping",), ("wrong_diagnosis",)])
def test_evidence_guard_recovery_budget_and_no_answer_fallback(behavior):
    from dqagent.evaluate import make_cases, solve
    case = next(c for c in make_cases(43, 16) if c["mask"] == 3)
    queries = [{"tool": name} for name in ["duplicates", "null_amounts", "freshness", "volume"]]
    correct = {"findings": [{"code": "duplicate_orders", "evidence": "duplicates"},
                            {"code": "missing_amounts", "evidence": "null_amounts"}]}
    replies = ([{"findings": []}] * 6 if behavior == "keep_stopping" else
               [{"findings": []}] + queries + [correct if behavior == "recover" else {"findings": []}])
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"message": {"content": json.dumps(replies[len(requests)-1])}}]}).encode())
        def log_message(self, *_):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = solve(case, "agent", Chat("protocol-test", f"http://127.0.0.1:{server.server_port}/v1", "fake-key"))
        assert result["success"] == (behavior == "recover")
        assert len(result["calls"]) == len(requests) == 6
        assert result["unchanged"] and result["agent_protocol_version"] == 2
        assert result["rejected_final_answers"][0]["reason"] == "insufficient_evidence"
        assert json.loads(requests[1]["messages"][-1]["content"])["final_answer_accepted"] is False
        assert result["status"] == ("incomplete" if behavior == "keep_stopping" else "ok")
        assert result["tool_calls"] == (0 if behavior == "keep_stopping" else 4)
        if behavior != "recover":
            assert result["findings"] == [] and result["false_negatives"] == 2
        for request in requests:
            assert all('"mask"' not in message["content"] and '"expected"' not in message["content"] for message in request["messages"])
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_published_failure_report_and_fresh_seed_are_reproducible():
    from dqagent.evaluate import make_cases
    report = json.loads(Path("evaluation/before/2026-10-22-six-cases.json").read_text())
    assert report["cases"] == make_cases(2604, 6)
    assert report["summary"]["methods"]["agent"]["successes"] == 1
    assert make_cases(2605, 6) != report["cases"]
    assert {case["mask"] for case in make_cases(2605, 16)} == set(range(16))


def test_http_rejection_keeps_reason_and_redacts_credentials(tmp_path):
    import urllib.error
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"code": "json_validate_failed", "message": "Rejected diagnostic-test-key; gsk_otherSensitiveToken; Bearer anotherPrivateToken"}}).encode())
        def log_message(self, *_):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        path = tmp_path / "calls.json"
        chat = Chat("protocol-only", f"http://127.0.0.1:{server.server_port}/v1", "diagnostic-test-key", json_mode=True, trace_path=path)
        with pytest.raises(urllib.error.HTTPError) as error:
            chat.ask([{"role": "user", "content": "Return JSON"}])
        assert error.value.code == 400
        saved = json.loads(path.read_text())
        assert len(saved) == 1 and saved[0]["http_status"] == 400
        assert "json_validate_failed" in saved[0]["provider_error_body"]
        assert all(secret not in path.read_text() for secret in ["diagnostic-test-key", "gsk_otherSensitiveToken", "anotherPrivateToken"])
        assert saved[0]["response"] is None
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
