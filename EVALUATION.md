# Real model evaluation

**Status: evaluation runner implemented; no real model results published yet.**
The existing demo reports verify fixtures. They do not measure an LLM's success rate.
A passing software test or the local HTTP protocol test below is not a real model run.

## Run a concrete comparison

1. Open this repository's **Settings → Secrets and variables → Actions**.
2. Add a repository secret named `LLM_API_KEY` with your provider API key. Never put it in code, a commit, an issue, or a chat.
3. Optional: set repository variable `LLM_BASE_URL` to your trusted provider's chat-completions base URL (ending in `/v1` where applicable). The default is `https://api.openai.com/v1`. Providers must support `messages`, `temperature`, and `max_tokens`; incompatible requests count as errors, with no fake fallback.
4. Open **Actions → Live model comparison → Run workflow**. Enter the provider's exact model ID and start with **1 case, 1 repeat**. This makes paid API calls to your account. Check provider billing before expanding the run.
5. Download the `live-model-comparison` artifact. It contains JSON and escaped HTML with per-attempt outcomes, model responses, paired comparisons, timings, hashes, and provider-reported token usage. Use only these live outputs for performance claims.

The workflow never runs on a push or a pull request. Unit-test CI needs no model key.
Artifacts contain synthetic inputs and model outputs; inspect them before making them public.
A provider request timeout or malformed response fails that attempt. Errors remain in the denominator;
raw worker stderr is deliberately omitted from reports to avoid credential disclosure.
A run with worker errors exits nonzero after saving its full report.
Runs checkpoint after every attempt and refuse to overwrite an existing report. Interrupted runs have
`complete: false`; do not present them as completed benchmarks. Failed workers may have consumed
provider tokens that are not available in the report; total observed calls/usage is a lower bound when errors occur.

## Local execution (Linux/macOS with `timeout`, or Linux container)

Set `LLM_API_KEY` securely in your shell, and optionally `LLM_BASE_URL`, then run from the repository root:

```bash
python -m dqagent.evaluate --model YOUR_MODEL_ID --limit 24 --seed 2604 --repeats 1 --output results/run-001.json
```

## Protocol and interpretation

A seeded generator creates 24 shuffled cases with varying volumes, amounts, duplicate multiplicities,
missing amounts, missing batches, mixed faults, and genuine revenue decline. The first 16 cases before
shuffling cover every combination of four mutation flags. The oracle comes from the mutations,
not from a model or the baseline. Labels, seeds, and generator internals are never sent to the model.
These remain synthetic public cases. New seeds vary data, not fault families; they do not prove
production generalization. Freeze the seed and dataset hash before tuning prompts.

Three methods use identical read-only tools and contract:

- `rules`: the existing deterministic five-check pipeline (zero model calls).
- `single_shot`: all five query results, followed by one model diagnosis call.
- `agent`: model chooses up to five distinct allowlisted tools and returns its own diagnosis,
  with up to six model calls including the final answer. It may finish early.

A success requires the exact set of fault codes and a corresponding observed tool citation for every
finding; unsupported and duplicate findings fail. A healthy diagnosis must observe all four fault checks. Reports also include false positives/negatives.
Read-only snapshot checks detect changes. Arbitrary SQL and repeated/invented tools are rejected.
These tasks have known rules, so the deterministic baseline should be strong. Matching it with more
cost does not show an accuracy benefit; fewer tool calls, fewer errors, or performance on genuinely
new, independently labeled cases would be needed to argue value. Tool selection is budgeted but
methods are not compute matched. A revenue decline alone must not be labeled a quality violation.
Maximum calls per full 24-case repeat: **168**, each requesting at most 1,600 output tokens.

## What to publish after running

Record the commit, dataset hash, provider/model ID, date, number of cases and repeats, success/error
counts for every method, paired wins/losses, latency, tool/model calls, available token usage,
and representative failures. Publish complete outcomes even if the agent loses to the baseline.
Do not convert a tiny benchmark percentage into a promise of job selection or production reliability.
