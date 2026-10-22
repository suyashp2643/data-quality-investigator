import argparse
import html
import json
import tempfile
from pathlib import Path

from .core import BaselinePlanner, Contract, LLMPlanner, ReviewStore, Warehouse, investigate, seed


def main():
    parser = argparse.ArgumentParser(description="Data quality investigation with constrained tools")
    parser.add_argument("command", choices=["demo", "investigate", "evaluate", "review"])
    parser.add_argument("--database", default="orders.sqlite")
    parser.add_argument("--postgres", action="store_true")
    parser.add_argument("--scenario", default="duplicates")
    parser.add_argument("--model")
    parser.add_argument("--question", default="Why did reported revenue change yesterday?")
    parser.add_argument("--expected-day", default="2026-10-21")
    parser.add_argument("--minimum-rows", type=int, default=5)
    parser.add_argument("--output", default="report.json")
    parser.add_argument("--reviewer")
    parser.add_argument("--decision", choices=["approve_proposal", "reject"])
    parser.add_argument("--store", default="reviews.sqlite")
    args = parser.parse_args()
    if args.command == "evaluate":
        expectations = {"healthy": [], "duplicates": ["duplicate_orders"], "nulls": ["missing_amounts"], "stale": ["stale_data", "low_volume"], "missing_batch": ["low_volume"], "business_decline": []}
        results = []
        with tempfile.TemporaryDirectory() as directory:
            for scenario, expected in expectations.items():
                path = Path(directory) / f"{scenario}.sqlite"
                seed(path, scenario)
                warehouse = Warehouse(str(path))
                report = investigate(warehouse, BaselinePlanner(), args.question, Contract())
                warehouse.close()
                observed = [finding["code"] for finding in report["findings"]]
                results.append({"scenario": scenario, "expected": expected, "observed": observed, "passed": set(expected) == set(observed)})
        output = {"mode": "deterministic_fixture_baseline_NOT_LLM_benchmark", "passed": sum(row["passed"] for row in results), "total": len(results), "results": results}
    else:
        if args.command == "demo":
            seed(Path(args.database), args.scenario)
        warehouse = Warehouse(args.database, args.postgres)
        if args.command == "review":
            store = ReviewStore(Path(args.store))
            store.review(json.loads(Path(args.output).read_text()), warehouse.snapshot(), args.reviewer or "", args.decision or "")
            store.close()
            warehouse.close()
            print("Review recorded. No warehouse writes executed.")
            return
        output = investigate(warehouse, LLMPlanner(args.model) if args.model else BaselinePlanner(), args.question, Contract(args.expected_day, args.minimum_rows))
        warehouse.close()
    Path(args.output).write_text(json.dumps(output, indent=2) + "\n")
    Path(args.output).with_suffix(".html").write_text("<!doctype html><meta charset='utf-8'><title>Investigation report</title><style>body{max-width:1000px;margin:40px auto;font:16px system-ui;background:#101827;color:#e2e8f0}pre{white-space:pre-wrap;background:#1e293b;padding:24px;border-radius:12px}</style><h1>Data quality investigation</h1><pre>" + html.escape(json.dumps(output, indent=2)) + "</pre>")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
