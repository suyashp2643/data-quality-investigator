# Real model evaluation

**Status: initial live results published; the revised agent has not yet been evaluated with a real model.**
See [recorded results and revision notes](evaluation/README.md).
The existing demo reports verify fixtures. They do not measure an LLM's success rate.
A passing software test or the local HTTP protocol test below is not a real model run.

## Run a concrete comparison

1. Open this repository's **Settings → Secrets and variables → Actions**.
2. Add a repository secret named `LLM_API_KEY` with your provider API key. Never put it in code, a commit, an issue, or a chat.
3. Optional: set repository variable `LLM_BASE_URL` to your trusted provider's chat-completions base URL (ending in `/v1` where applicable). The default is `https://api.openai.com/v1`. Providers must support `messages`, `temperature`, `max_tokens`, JSON Object Mode for the baseline, and strict JSON Schema output for the agent; incompatible requests count as errors, with no fake fallback.
4. Open **Actions → Live model comparison → Run workflow**. Enter the provider's exact model ID and start with **1 case, 1 repeat, seed 2605**. Seed 2604 is now development data. This makes paid API calls to your account. Check provider billing before expanding the run.
5. Download the `live-model-comparison` artifact. It contains JSON and escaped HTML with per-attempt outcomes, model responses, paired comparisons, timings, hashes, and provider-reported token usage. Use only these live outputs for performance claims.

The workflow never runs on a push or a pull request. Unit-test CI needs no model key.
Artifacts contain synthetic inputs and model outputs; inspect them before making them public.
A provider request timeout or malformed response fails that attempt. Errors remain in the denominator;
raw worker stderr is deliberately omitted from reports to avoid credential disclosure.
A run with worker errors exits nonzero after saving its full report.
Runs checkpoint after every attempt and refuse to overwrite an existing report. Interrupted runs have
`complete: false`; do not present them as completed benchmarks. Received model responses are checkpointed before parsing, including finish reason and token usage.
Responses from failed workers are retained in the report. Calls that time out or fail before a response
may have consumed provider tokens that are not available in the report; total observed calls/usage is a lower bound when errors occur.

## Local execution (Linux/macOS with `timeout`, or Linux container)

Set `LLM_API_KEY` securely in your shell, and optionally `LLM_BASE_URL`, then run from the repository root:

```bash
python -m dqagent.evaluate --model YOUR_MODEL_ID --limit 16 --seed 2605 --repeats 1 --output results/run-001.json
```

## Protocol and interpretation

A seeded generator creates 24 shuffled cases with varying volumes, amounts, duplicate multiplicities,
missing amounts, missing batches, mixed faults, and genuine revenue decline. The first 16 cases before
shuffling cover every combination of four mutation flags. The oracle comes from the mutations,
not from a model or the baseline. Labels, seeds, and generator internals are never sent to the model.
These remain synthetic public cases. New seeds vary data, not fault families; they do not prove
production generalization. Freeze the seed and dataset hash before tuning prompts. The six seed-2604 cases have already
been used to diagnose premature stopping; do not describe them as unseen evaluation data.

Three methods use identical read-only tools and contract:

- `rules`: the existing deterministic five-check pipeline (zero model calls).
- `single_shot`: all five query results, followed by one model diagnosis call.
- `agent`: model chooses up to five distinct allowlisted tools and returns its own diagnosis,
  with up to six model calls including the final answer. Protocol v2 requires observations from
  duplicates, null_amounts, freshness and volume before accepting any final answer. Early final
  answers are rejected with corrective feedback and consume a call. Exhausting the budget returns
  `incomplete` and fails the attempt; the model's answer is never replaced by the rules baseline.
  The model chooses tool order; it can omit the optional revenue check. This completeness guard
  reduces its discretion and does not establish an advantage over deterministic checks.

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

## JSON output transport revision

The earlier transport revision requested provider JSON Object Mode (`response_format: {"type":"json_object"}`) for both model methods. Protocol v3 below replaces the agent format; the baseline retains JSON Object Mode.
The output must still pass the existing response shape, tool allowlist, evidence guard and scoring checks.
JSON syntax is not proof of a correct diagnosis. No malformed answer is rewritten, retried invisibly,
or replaced by the rules baseline. The six-call and 1,600-output-token limits remain unchanged.
Malformed and truncated responses remain failed attempts. Failed-worker response bodies, usage and
finish reasons are retained so that formatting failures can be distinguished from token truncation.
Earlier reports used prompt-only formatting; compare all methods again under the recorded new
transport configuration before making performance claims. The authenticated live outcome is pending.

Provider reference: https://console.groq.com/docs/structured-outputs#json-object-mode

HTTP errors now retain a bounded provider error body in the failed call record, with the
configured API key, common API-key patterns and Bearer tokens redacted. Raw error bodies are
not printed in workflow logs. An HTTP error still fails the attempt; it is not retried or
reclassified as a successful diagnosis. Review the artifact before publishing it.

## Protocol v3: one action per response

The recorded [failed run](evaluation/failures/2026-10-22-json-concatenation.json) contains
Groq error `json_validate_failed`. Its failed generation concatenated multiple query objects
repeatedly. Two prior tool requests succeeded before the provider rejected that generation.
This is not an authentication or warehouse-write failure.

The agent now uses strict JSON Schema output (`json_schema`, `strict: true`) with exactly two
required fields: `tool` and `findings`. A query is `{"tool":"freshness","findings":null}`;
a final answer is `{"tool":null,"findings":[]}` or a findings array. The prompt requires one
object and then a stop until the host returns the real query result. The controller rejects
simultaneous query/final decisions, and preserves the four-check evidence guard and six-call cap.
No native provider tools or streaming are combined with structured output. Provider support for
strict schema mode is required; GPT-OSS 120B is listed by Groq as supporting it.

The baseline still uses the previous JSON Object Mode. The agent configuration now includes
its stricter output constraint; the comparison is between complete configurations, not an
isolated test of orchestration. Scoring and fault labels are unchanged. Reports record agent
protocol version 3 and both output formats. No new model success rate is claimed yet.
