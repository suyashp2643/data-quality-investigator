# Data Quality Investigator

## Model comparison

See [EVALUATION.md](EVALUATION.md) for a seeded mixed-fault comparison of rules, single-shot diagnosis, and adaptive tool use. Initial live results are [published](evaluation/README.md): the agent passed 1/6 cases while both baselines passed 6/6. An evidence guard is implemented; revised live performance is pending.

An evidence-first investigation prototype with constrained model tools, deterministic checks, data fingerprinting, and durable proposal reviews.

## Status

Runnable SQLite demo; optional OpenAI-compatible model planner and PostgreSQL connector implemented but not validated against live external services. The model chooses the next tool; deterministic code evaluates contract violations. It does not autonomously establish root cause or execute repairs. This is a portfolio prototype, not a production monitoring platform.

## Quick start — no API key or Docker required

Python 3.10+; run from this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest tests -q
python -m dqagent demo --database demo.sqlite --scenario duplicates --output report.json
python -m dqagent evaluate --output evaluation.json
python -m dqagent review --database demo.sqlite --output report.json --reviewer suyash --decision approve_proposal
```

Open `report.html` to inspect evidence. Demo creation refuses to overwrite an existing database; choose another filename for a second run. The expected date is deliberately fixed for reproducible fixtures. For your data pass `--expected-day YYYY-MM-DD --minimum-rows N`.

## Investigation flow

Question → planner → allowlisted read tool → SQL evidence → next tool → deterministic contract checks → fingerprinted JSON/HTML report → human proposal review.

The five tools inspect volume, duplicate order IDs, null amounts, freshness and revenue. A five-step bound prevents loops. Unknown/repeated tools fail closed. SQLite opens read-only; PostgreSQL sets read-only transactions. Data is fingerprinted before/after investigation and checked at review. The review ledger rejects modified reports, stale data and duplicate decisions. Hashes detect changes; they are not cryptographic proof of reviewer identity. The reviewer's name is self-reported. Reports include row-level evidence: use synthetic/non-sensitive data.

## Model planner (optional)

Set `LLM_API_KEY`, `LLM_BASE_URL` (default OpenAI-compatible `/v1` endpoint), and run:

```bash
python -m dqagent investigate --database demo.sqlite --model YOUR_MODEL --output live.json
```

Use a local compatible endpoint for no paid calls, if available. Model API usage may cost money. Five calls maximum per investigation, 100 requested output tokens/call and a 30-second request timeout; there is no dollar-cost meter. Invalid JSON or tools stop execution rather than falling back silently. Model evidence and your question are sent to the endpoint you configure.

## PostgreSQL (optional; integration not yet verified)

Install `python -m pip install -e '.[postgres]'`. Use a dedicated read-only DB role; do not use production credentials. Create this small fixture schema in a development database:

```sql
CREATE TABLE orders(order_id TEXT, day TEXT, amount DOUBLE PRECISION);
```

The day column must contain ISO dates. Use `python -m dqagent investigate --postgres --database "$DQ_DATABASE_URL" --expected-day 2026-10-21`. The connection string is never included in reports. Current implementation reads all order rows for fingerprinting, so it is intended for small tables, not warehouse-scale deployments. It does not guarantee a consistent snapshot under concurrent PostgreSQL writes; investigate a stable snapshot.

## Evaluation

Six public synthetic scenarios: healthy, duplicate orders, null amounts, stale data, missing batch and genuine business decline. The bundled `evaluation.json` verifies the deterministic baseline only. It is **not** an LLM success rate or held-out benchmark. `VERIFICATION.md` records checks run in this environment.

## Provenance and contributions

This implementation was authored with AI assistance for Suyash Patil. No source code was copied from the reference repository. The conceptual reference is [atulpandey02/agentic-dq-monitor](https://github.com/atulpandey02/agentic-dq-monitor), inspected at commit `4a851d42dade969432d896d7b1a3edf336334078`. Its README declared MIT but its checkout contained no license file; its code is not redistributed here.

Implementation added here: SQLite demo, optional PostgreSQL adapter, restricted planner tools, evidence reports, snapshot-bound proposal reviews and synthetic evaluation fixtures. There is no LangGraph, Airflow or Snowflake integration in this implementation. Review, understand and run the code yourself before describing ownership in interviews.

## Next substantive milestones

- Validate PostgreSQL integration using a stable transaction snapshot.
- Evaluate the live planner against a fixed baseline on unseen incidents.
- Add schema drift and broken-join investigations, grounded pipeline-log tools and recovery.
- Add authentication and signed reviewer decisions before offering real repair execution.

## License

MIT, covering the original implementation in this repository. See LICENSE.
