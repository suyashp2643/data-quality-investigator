"""Small auditable chat-completions client and paired evaluation driver."""
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Chat:
    def __init__(self, model: str, endpoint: str | None = None, key: str | None = None):
        self.model = model
        self.endpoint = endpoint or os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
        self.key = key if key is not None else os.environ["LLM_API_KEY"]
        self.calls = []

    def ask(self, messages: list[dict]) -> dict:
        payload = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": 1600}
        request = urllib.request.Request(self.endpoint.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "User-Agent": "agent-evaluation/1.0", "Authorization": "Bearer " + self.key})
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.load(response)
        content = body["choices"][0]["message"]["content"]
        self.calls.append({"request_hash": digest(payload), "response": content,
            "returned_model": body.get("model"), "usage": body.get("usage"),
            "seconds": round(time.monotonic() - started, 3)})
        return json.loads(content)


def summarize(rows: list[dict]) -> dict:
    methods = sorted({r["method"] for r in rows})
    summary = {}
    for method in methods:
        items = [r for r in rows if r["method"] == method]
        summary[method] = {"attempts": len(items), "successes": sum(r.get("success", False) for r in items),
            "success_rate": sum(r.get("success", False) for r in items) / len(items),
            "errors": sum(r.get("status") == "error" for r in items),
            "total_calls": sum(len(r.get("calls", [])) for r in items),
            "total_seconds": round(sum(r["seconds"] for r in items), 3),
            "observed_total_tokens": sum((call.get("usage") or {}).get("total_tokens", 0) for r in items for call in r.get("calls", [])),
            "calls_without_token_usage": sum(not (call.get("usage") or {}).get("total_tokens") for r in items for call in r.get("calls", []))}
        if any("false_positives" in r for r in items):
            summary[method].update({name: sum(r.get(name, 0) for r in items) for name in ("true_positives", "false_positives", "false_negatives")})
    paired = {}
    for method in methods:
        paired[method] = {(r["case"], r["repeat"]): bool(r.get("success")) for r in rows if r["method"] == method}
    comparisons = []
    for baseline in methods:
        if baseline == "agent":
            continue
        keys = paired[baseline].keys() & paired.get("agent", {}).keys()
        comparisons.append({"baseline": baseline, "pairs": len(keys),
            "agent_only_success": sum(paired["agent"][k] and not paired[baseline][k] for k in keys),
            "baseline_only_success": sum(paired[baseline][k] and not paired["agent"][k] for k in keys)})
    return {"methods": summary, "paired": comparisons}


def worker_error(stderr: str, returncode: int) -> dict:
    """Whitelist failure categories; never publish raw provider messages or tracebacks."""
    stderr = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", stderr)
    status = re.search(r"HTTP Error\s+(\d{3})", stderr)
    categories = {400: "provider_rejected_request", 401: "provider_authentication_failed",
        403: "provider_access_denied", 404: "provider_model_or_endpoint_not_found",
        429: "provider_rate_limit_or_quota"}
    if status:
        code = int(status.group(1))
        return {"returncode": returncode, "http_status": code,
            "category": categories.get(code, "provider_http_error")}
    markers = {"JSONDecodeError:": "model_returned_invalid_json", "KeyError:": "response_missing_required_field",
        "ModuleNotFoundError:": "missing_dependency", "TimeoutExpired:": "sandbox_timeout",
        "TimeoutError:": "provider_timeout", "URLError:": "provider_connection_failed",
        "SyntaxError:": "worker_syntax_error", "ValueError:": "invalid_response_or_tool",
        "TypeError:": "unexpected_response_type", "ImportError:": "dependency_import_failed",
        "RemoteDisconnected:": "provider_disconnected", "PermissionError:": "worker_permission_error"}
    category = next((name for marker, name in markers.items() if marker in stderr),
                    "worker_timeout" if returncode == 124 else "worker_failed")
    names = re.findall(r"^([A-Za-z_][A-Za-z0-9_.]{0,100}):", stderr, re.MULTILINE)
    result = {"returncode": returncode, "category": category}
    if names:
        result["exception_type"] = names[-1]
    if "Usage:" in stderr and returncode == 2:
        result["category"] = "worker_cli_arguments_rejected"
    return result


def run_matrix(module: str, cases: list[dict], methods: list[str], model: str, output: Path, repeats: int = 1) -> dict:
    if not 1 <= repeats <= 5 or not model:
        raise ValueError("Specify a model and between 1 and 5 repeats")
    if not os.environ.get("LLM_API_KEY"):
        raise ValueError("Set LLM_API_KEY locally or as a GitHub Actions secret; never paste it in chat")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError("Choose a new output path to preserve previous runs")
    report = {"mode": "live_model_evaluation", "started_at": datetime.now(timezone.utc).isoformat(),
        "model": model, "commit": os.environ.get("GITHUB_SHA"),
        "code_hashes": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(module.split(".")[0]).glob("*.py")},
        "dataset_hash": digest(cases), "cases": cases, "repeats": repeats,
        "max_output_tokens_per_call": 1600, "results": [],
        "limitations": "Small public benchmark; prompt-hidden tests are not contamination-proof. Failures remain in denominator. No production reliability claim. Token usage is provider-reported, not dollar cost."}
    with tempfile.TemporaryDirectory() as directory:
        for repeat in range(repeats):
            for case in cases:
                order = methods if (repeat + cases.index(case)) % 2 == 0 else list(reversed(methods))
                for method in order:
                    request = Path(directory) / "request.json"
                    result = Path(directory) / "result.json"
                    result.unlink(missing_ok=True)
                    request.write_text(json.dumps({"case": case, "method": method, "model": model, "result": str(result)}))
                    row = {"case": case["id"], "repeat": repeat, "method": method, "status": "error", "success": False}
                    started = time.monotonic()
                    # OS timeout also bounds repeated model calls. Child errors cannot silently drop an attempt.
                    process = subprocess.run(["timeout", "420", sys.executable, "-m", module, "--worker", str(request)], capture_output=True, text=True, env=dict(os.environ, TYPER_STANDARD_TRACEBACK="1", NO_COLOR="1"))
                    if process.returncode == 0 and result.exists():
                        row.update(json.loads(result.read_text()))
                    else:
                        row["error"] = worker_error(process.stderr, process.returncode)
                    row["seconds"] = round(time.monotonic() - started, 3)
                    report["results"].append(row)
                    report["summary"] = summarize(report["results"])
                    report["complete"] = len(report["results"]) == len(cases) * len(methods) * repeats
                    output.write_text(json.dumps(report, indent=2) + "\n")
                    output.with_suffix(".html").write_text("<!doctype html><meta charset=utf-8><title>Paired evaluation</title><h1>Paired evaluation</h1><pre>" + html.escape(json.dumps(report, indent=2)) + "</pre>")
                    print(case["id"], method, row["status"], row.get("error", {}).get("category", ""), json.dumps(row.get("error", {}), sort_keys=True), flush=True)
    if any(row["status"] == "error" for row in report["results"]):
        raise SystemExit("Evaluation finished with failed workers; inspect the report. No attempts were dropped.")
    return report
