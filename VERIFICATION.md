# Verification — 22 October 2026

Python 3.12.

- `python -m pytest tests -q`: **9 passed**.
- `python -m dqagent evaluate --output evaluation.json`: **6/6 deterministic synthetic scenarios** matched expected contract findings.
- SQLite demo: JSON and HTML evidence reports generated.
- Review CLI: approval of proposal recorded without warehouse writes.
- Tests cover read-only enforcement, unauthorized tools, partial investigations, altered reports, stale snapshots and duplicate reviews. A local HTTP server verifies model response parsing and rejection of unauthorized tool selection.

No paid API calls or live model benchmark was run. PostgreSQL adapter is not integration-tested. This is a five-tool contract-checking prototype; it does not prove root cause, diagnose arbitrary schemas or execute corrective SQL.
