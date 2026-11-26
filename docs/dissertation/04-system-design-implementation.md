# Chapter 4 — System Design and Implementation

> **Draft status (2026-11-25).** Describes the implementation as frozen at commit `c5448ef` (tag `test-freeze`,
> branch `logagent-rca`). No test results are reported. **[OPEN]** marks items needing confirmation;
> **[CITATION NEEDED]** marks unverified sources.

## 4.1 Overview

The framework proposed in this dissertation is implemented as the Python package `logagent_rca`
(internally named LogAgent-RCA to avoid a name clash with an unrelated system called AgentRCA,
arXiv:2607.22385; D-006). It diagnoses one incident at a time from a case bundle of log files and produces a
structured root-cause report. Inference uses a locally hosted open-weight model through Ollama; no external
service is contacted.

The implementation is organised so that the diagnosis strategies under comparison (Chapter 3) differ only in
how evidence is selected. Ingestion, token accounting, the output schema, validation and scoring are shared.
An earlier exploratory prototype (package `agentrca`, branch `poc-preservation`, commit `e7bdd9d`) informed the
design; it is preserved unchanged and is not part of the evaluated system.

**Technology.** Python 3.12; Pydantic 2.14.4 (schemas and configuration); PyYAML 6.0.3; Hugging Face
`tokenizers` 0.23.3 with the Qwen3-8B `tokenizer.json`; psutil 7.2.2; NumPy 2.5.5 and SciPy 1.18.1 (statistics);
pytest 9.2.0. The model is `qwen3:8b` (8.2B parameters, Q4_K_M quantisation) served by Ollama 0.40.16 on CPU
**[CITATION NEEDED — Qwen3 model card / technical report; Ollama project page]**. Agent frameworks (for example
LangGraph) and vector databases were deliberately not used: the controller logic is explicit code so that each
mechanism can be inspected, tested and switched off for ablation.

## 4.2 Architecture

```
            case bundle (incident.json + *.log)            ground truth (separate directory)
                         │                                            │
                 ┌───────▼────────┐                                   │
                 │ ingest + index │  safe parsing, sanitising         │
                 └───────┬────────┘                                   │
          ┌──────────────┼──────────────┬──────────────┐              │
     ┌────▼────┐   ┌─────▼──────┐  ┌────▼──────────────▼───┐          │
     │ E1 / E1f│   │ E2b: extract│  │ E3 / A2: agent loop   │          │
     │ rules   │   │ + one call  │  │ + read-only tools     │          │
     └────┬────┘   └─────┬──────┘  │ + coverage gate (E3)  │          │
          │              │         └──────────┬────────────┘          │
          │   shared evidence ledger (strict B), shared prompt/schema │
          └──────────────┴──────────┬─────────┘                       │
                             ┌──────▼──────┐                          │
                             │  validator  │  raw + validated report  │
                             └──────┬──────┘                          │
                             ┌──────▼──────┐                   ┌──────▼──────┐
                             │   runner    │── run records ───►│  metrics +  │
                             │ (audit, CPU,│                   │  statistics │
                             │  memory)    │                   └─────────────┘
                             └─────────────┘
```

Only the metrics module reads ground truth; it runs after the diagnosis runs are recorded.

## 4.3 Module implementation (M1–M11)

Each module was implemented, tested and committed before the next was started.

| Module | Commit | Files | Responsibility | Tests |
|---|---|---|---|---|
| M1 | `7156170` | `schemas.py`, `config.py` | Data contracts and validated, immutable configuration | 31 |
| M2 | `8925d02` | `ingest.py`, `index.py`, `tokens.py`, `evidence.py`, `calibrate.py` | Safe ingestion, read-only index, exact token counting, evidence ledger | 27 |
| M3 | `a4a6c25` | `synth/`, `truth.py` | Synthetic generator, development/test families, ground-truth store | 14 |
| M4 | `8eb8300` | `context.py`, `e1.py` | E1 rule-based RCA and E1f floor | 7 |
| M5 | `c36f7d9` | `llm.py`, `resources.py`, `prompts.py`, `extract.py`, `finalize.py`, `e2b.py` | Ollama client, shared prompts and final call, E2b | 9 |
| M6 | `4aae7f6` | `safety.py`, `tools.py` | Tool allowlist, argument validation, audit log, read-only tools | 19 |
| M7 | `7585cec` | `agent.py` | E3 controller loop | 7 |
| M8 | `c0a521a` | `coverage.py` | Coverage gate (A2: disabled) | 5 |
| M9 | `d492861` | `validator.py` | Claim-level grounding validator | 11 |
| M10 | `e4ba766` | `runner.py`, `metrics.py`, `stats.py`, `analyze.py`, `__main__.py` | Experiment runner, scoring, statistics, command line | 13 |
| M11 | `a4e2666` | `resources.py` (rewrite) and metric fields | Corrected memory and CPU measurement; persisted truncation counts | 11 |

The repository contains 166 automated tests (the 154 above plus 12 for the preserved prototype), all passing at
the freeze commit. None requires the LLM; LLM behaviour is simulated with a scripted stand-in.

## 4.4 Data contracts and configuration (M1)

All data passed between modules is defined by Pydantic models that forbid unknown fields and are immutable after
creation. The most important are:

* **`LogEvent`**: a parsed log line with a stable identifier `<source>:<line>`, a UTC timestamp, a normalised
  severity (DEBUG, INFO, WARN, ERROR, FATAL; aliases such as WARNING, SEVERE and CRITICAL are mapped), a
  component name restricted to a safe character set, and a flag for suspected prompt injection.
* **`CaseManifest`**: the agent-visible `incident.json`. Because unknown fields are rejected, ground-truth fields
  cannot be written into a case bundle.
* **`GroundTruth`**: root causes, key and relevant evidence, propagation path, stratum and family, with
  consistency rules (for example, key evidence must be a subset of relevant evidence; abstention cases must
  expect abstention).
* **`FinalReport`**: the single output schema used by every LLM arm: at most three ranked hypotheses, each with a
  component, a summary, a confidence in [0, 1] and one to three claims citing evidence identifiers; at most two
  evidence gaps and two recommendations; text fields of at most 160 characters.
* **`RunRecord`** and **`RunMetrics`**: the complete record of one run (Section 4.12). `RunMetrics` rejects any
  run whose unique evidence tokens exceed B.

The configuration (`configs/test.yaml`) is loaded into frozen sections. Validation rejects overlapping case and
truth directories, an output directory inside the case directory, a budget that would not fit the context window
(B + prompt overhead + maximum output ≤ context length), unknown tools and malformed log-format patterns.
A SHA-256 hash of the configuration values is stored with every run.

## 4.5 Log ingestion and normalisation (M2)

`ingest.py` reads one case bundle under the following rules:

* **Containment.** Only files listed in `incident.json` are read; each must resolve to a regular file inside the
  case directory. Absolute paths, `..` and symbolic links leaving the directory are rejected.
* **Bounded reading.** At most 200,000 lines and 20 MB per file; invalid UTF-8 is replaced rather than causing
  failure.
* **Parsing.** A configurable regular expression extracts timestamp, level, component and message. Timestamps in
  ISO-8601 form, with `Z`, offsets or comma decimals, are converted to UTC; timestamps without a zone are taken as
  UTC. Indented continuation lines (for example stack traces) are appended to the preceding event. Unparsed lines
  are counted.
* **Sanitising untrusted text.** Messages are Unicode-normalised (NFC); control, zero-width and bidirectional
  override characters are removed; whitespace is collapsed; credentials, bearer tokens, key-like strings and
  e-mail addresses are redacted; the framework's own delimiter tags are neutralised; citation-like labels such
  as `[E12]` in log text are rewritten as `(E12)` so that log content cannot forge an evidence reference;
  messages are truncated to 400 characters.
* **Injection flagging.** Messages matching instruction-like patterns (for example "ignore previous
  instructions" or a request to call a tool) are flagged as suspicious. Flagged lines remain visible as data but
  can never support a claim (Section 4.10).

The parsed events are held in a read-only, time-ordered index (`index.py`) supporting filtered search,
context around an event, and per-component problem events.

## 4.6 Evidence budget and token accounting (M2)

`evidence.py` implements the evidence ledger shared by all arms (definition in Chapter 3, §3.8):

* Each item is rendered as `[E<n>] <timestamp> <SEVERITY> <component> (<source>:<line>) <message>`; its cost is
  the exact token count of that line plus a newline, computed by `tokens.py` with the Qwen3-8B tokenizer. The
  tokenizer file's SHA-256 (`aeb13307…dae4`) and the `tokenizers` version are verified on every load.
* Items are identified by their event identifier. A new item receives the next label (`E1`, `E2`, …) and is
  charged once; an already-presented item is returned with its existing label at no cost and counted as a
  repeated exposure.
* Admission is strict: an item is admitted only if used + cost ≤ B. Tool results stop at the first item that
  does not fit, preserving order; single-pass packing skips an oversized item and tries later ones.
* A test checks that rendering admitted items as one block never costs more than the sum of their charges plus
  the fixed framing, so per-item charging cannot under-count what the model sees.

Calibration against Ollama (`calibrate.py`) showed that Ollama's reported prompt count exceeded the framework's
count of the message text by a constant 16 tokens (one user message) or 21 tokens (system and user messages).

## 4.7 Synthetic data generation (M3)

The generator (`synth/engine.py`) builds a case from a family template and a seed derived deterministically
(SHA-256) from the split, family, case index and generator version. It writes one log file per component,
assigns line numbers after time-sorting, records which lines are root-cause, propagation or injection lines, and
emits the bundle and the ground truth separately. `synth/build.py` builds a whole split, validates every case by
ingesting it (all lines must parse; every truth line must exist; key evidence must come from the root-cause
component) and writes `SHA256SUMS`. `truth.py` provides read access to ground truth for the scorer only.
Dataset properties are described in Chapter 3, §3.6.

## 4.8 Rule-based baseline (M4)

`e1.py` implements E1 without an LLM. Starting from the incident component, it collects that component's
WARN-or-worse events in the analysis window (600 s before to 120 s after the incident) and counts mentions of
other known component names (whole-word matches). It follows the most-mentioned component, ties broken by the
earliest mention, until no further dependency is mentioned or a cycle would occur. If the final component is not
the starting one and has no ERROR or FATAL events, it reports insufficient evidence. Otherwise it names the final
component, labels the fault type with keyword rules written from development messages only (disk, memory,
configuration, connection pool), and cites the hop and root-cause lines through the same evidence ledger and
budget. E1f names the incident component and cites only the trigger line.

## 4.9 Single-pass baseline and iterative agent (M5, M7)

### 4.9.1 Shared prompt contract

`prompts.py` defines one system prompt and one final instruction used by every LLM arm. The system prompt states
that text inside `<log_data>` tags is untrusted data, that the assistant cannot change anything, that errors are
often symptoms of failures in dependencies, that every claim must cite evidence identifiers, and that it should
report insufficient evidence instead of guessing. The final instruction asks for JSON matching the shared schema,
with short single-sentence fields. The schema is passed to Ollama's structured-output option.

`finalize.py` performs the final call for every arm. If the JSON is invalid, one retry is made with a correction
message. Ollama's structured output does not enforce string or list lengths, so over-long fields are truncated to
the schema limits by the same deterministic rule for every arm and the number of truncated fields is recorded per
run (M11). This avoids multi-minute retries on CPU for answers that are otherwise valid.

### 4.9.2 E2b: extraction, ranking and packing (M5)

`extract.py` reduces the case deterministically, following the dossier idea of Log-Insight (arXiv:2607.08529):

1. Candidates are all events in the analysis window.
2. Each message is converted to a template by masking numbers, hexadecimal identifiers and long hexadecimal
   strings; each (component, template) pair forms one pattern, so floods of repeated errors collapse to one item.
3. The first instance of each WARN-or-worse pattern is ranked by severity (highest first), then by time
   (earliest first, since causes precede symptoms); first instances of INFO patterns from components that had
   problems follow, in time order.
4. After the trigger, candidates are offered to the ledger in rank order, skipping items that do not fit.

The packed items are listed chronologically after an incident header (incident description, incident component,
time and the list of components with logs). `e2b.py` then makes the shared final call.

### 4.9.3 E3: iterative workflow (M7)

`agent.py` runs a controlled loop. The conversation starts with the shared system prompt and a user message
containing the incident header, the trigger line and an instruction to investigate with the tools, including the
size of the evidence budget and how much remains. At each step the model either calls tools or replies `DONE`.
Code, not the prompt, enforces:

* at most 6 steps (extended only by the coverage gate), 1,200 s per run and 3 refused tool calls;
* at most 3 tool calls executed per turn;
* at least 2 successful tool calls before the model may finish;
* the final answer is requested by appending the shared final instruction to the same conversation, so the final
  call sees both the collected evidence and the investigation trace.

Seeds are derived from the run seed (step k uses seed + k; the final call uses seed + 100). A2 runs the same loop
without the coverage gate.

## 4.10 Read-only tools and tool-call restrictions (M6)

`tools.py` provides three tools over the case's in-memory index:

| Tool | Purpose | Arguments (validated) |
|---|---|---|
| `error_timeline` | Earliest two WARN-or-worse events of each component, oldest first | optional minimum severity (WARN/ERROR/FATAL), start, end |
| `search_logs` | Events of one or all components, filtered by severity and substring | optional component, substring (≤ 80 chars, not a regular expression), minimum severity, start, end, limit 1–15 |
| `get_context` | Events immediately before and after an already-presented evidence item | evidence ID (required), before and after 0–8 |

No tool accepts a file path, command, URL or regular expression, and no tool reveals counts or other aggregates,
so all log-derived content the model sees passes through the evidence ledger. Every tool result is charged under
B; repeated items are shown as `[E3] (already shown)`, and the model is told when the budget is exhausted.

`safety.py` validates every request before execution: the tool must be on the configured allowlist; arguments
must be declared, of the declared type, within range, free of control characters, of bounded length and, for
times, valid ISO-8601. Refused requests return an error message to the model, are recorded in the audit log and
count towards the limit of refused calls. Tests cover requests such as an unknown `run_shell` tool, a path to a
ground-truth file, a regular-expression argument and out-of-range limits.

## 4.11 Coverage gate and grounding validator (M8, M9)

### 4.11.1 Coverage gate

`coverage.py` implements the coverage gate. When the agent tries to finish, or runs out of steps, the controller
lists components that logged WARN-or-worse events in the 600 s before the incident and that the agent has not
examined explicitly, either by `search_logs` restricted to that component or by `get_context` on one of its
evidence items. If any remain, finishing is refused and up to three of them are named, with their first problem
time. The gate acts for at most two rounds, each adding two steps, and is silent when fewer than 60 budget tokens
remain, since no further evidence line could then be shown. The mechanism addresses the "incomplete exploration"
failure reported for RCA agents (arXiv:2602.09937) at code level; the nearest prior mechanism found is RCAgent's
warning against early finalising (arXiv:2310.16340). In the development operational check at B = 900, the agent
often exhausted the budget, so the gate was frequently inactive (D-035).

### 4.11.2 Grounding validator

`validator.py` checks the raw report of every arm, claim by claim:

1. cited identifiers that were never presented in the run are removed and counted as fabricated;
2. evidence flagged as possible prompt injection is excluded from support;
3. a claim is supported if it shares at least two content words with its remaining cited evidence (component name
   and message), where words of five or more characters also match on a shared five-character prefix; otherwise
   the claim is removed.

A hypothesis is kept only if its component exists in the case and at least one supported claim cites evidence from,
or naming, that component. If no hypothesis survives, the validated report abstains. The raw report is preserved,
which allows A3 to be scored without an additional run. Similar mechanisms exist in prior work (RCAgent's evidence
filter, arXiv:2310.16340; a deterministic grounding check in arXiv:2606.08590); the contribution here is validation
of every claim of the final report, measured by ablation. The check is lexical and has not been compared with human
judgement **[OPEN]**.

## 4.12 Report generation, provenance and auditability (M10)

For every run, `runner.py` writes:

* **Run record** (`runs/<case>__<arm>__r<k>.json`): case, arm, repeat, configuration hash, code commit, model
  provenance (name, manifest digest, weights-file digest, quantisation, parameter size, Ollama version, context
  length, temperature, seed, thinking setting, output limit), start time, status, error, raw report, validated
  report, validator statistics, all evidence items with source, line, step, tool and token cost, all tool calls
  (allowed or refused, arguments, new evidence tokens, time) and the metrics.
* **Audit log** (`audit/<run>.jsonl`): append-only events, including tool calls, refused requests, injection
  flags, coverage-gate decisions and controller nudges.
* **Transcript** (`transcripts/<run>.json`): every message exchanged with the model.
* **Index** (`index.jsonl`) and an experiment-level `config.json` with the code commit, a dirty-tree flag and the
  full configuration.

`metrics.py` scores records against ground truth; `stats.py` and `analyze.py` produce the per-arm summary, the
primary and secondary comparisons with family-level statistics, per-stratum results, and Markdown and JSON reports
headed by a statement that the analysis is exploratory.

## 4.13 Error handling, resumability and instrumentation (M10, M11)

* **Resumability.** Run identifiers are deterministic; existing records are skipped; records are written to a
  temporary file and renamed, so an interruption cannot leave a partial record.
* **Integrity.** Before running, the dataset is verified file by file against the frozen checksums; the test split
  is refused from a working tree with uncommitted tracked changes.
* **Failures.** Invalid model output: one retry, then status `failed`. Infrastructure errors (for example a failed
  request to Ollama): up to two whole-run retries. Agent time or refusal limits end the loop and the final answer
  is still requested. Failed runs are recorded, not discarded.
* **CPU and memory (corrected in M11).** `resources.py` identifies the Ollama server by process name and includes
  its child processes (the `llama-server` runner), counting each process once. It records CPU seconds and mean CPU
  utilisation (100 × CPU seconds / wall time), and the peak of three memory measures: RSS, which can over-state
  shared pages; USS, memory unique to these processes; and PSS, the proportional share (Linux only). Host memory in
  use is recorded as context, since the server is shared. The original sampler matched command-line text and summed
  RSS. Investigation showed that the 15.3 GB peak seen in the pilot was nonetheless real memory: one runner whose
  Ollama host prompt cache (default 8,192 MiB) had filled to 8,178 MiB. After loading, the model process uses
  about 6.8 GB (D-032).

## 4.14 Measured latency and the "Real-Time" question

On the available hardware (shared four-core CPU, no GPU), generation runs at roughly 1.3–1.6 output tokens per
second under load and prompt processing at roughly 22–29 tokens per second (RD §12). Development measurements at
B = 900 gave median wall-clock times of 462 s for E2b, 750 s for E3 and 507 s for A2 per incident (D-035); E1 takes
under one second. These figures describe this environment only. The implementation therefore does not provide
diagnosis in seconds on this hardware. **[OPEN — Q-002]** The meaning of "Real-Time" in the title requires
supervisor clarification, for example as real-time detection with near-real-time diagnosis, or a revised title.

## 4.15 Implementation limitations

* Single local model and single CPU host; no GPU or laptop measurement yet.
* Synthetic data only; no public-dataset adapter in the frozen experiment.
* Lexical validator; no human-judgement check.
* Safety controls unit-tested but not evaluated adversarially with the LLM.
* Deferred features: dashboard, Docker packaging, additional ablations and baselines, speed optimisation (to be
  addressed after the controlled experiment).

---

### Open items for this chapter

| Ref | Item |
|---|---|
| Q-002 | Supervisor: "Real-Time" definition or title change |
| — | Citations needed: Qwen3 model card/technical report, Ollama, Pydantic, Hugging Face `tokenizers` |
| — | Confirm the Qwen3 licence from the official model card |
| — | Validator agreement with manual labels not measured |
| — | Safety: describe as implemented controls plus unit tests, not an adversarial evaluation |
| Q-015 | Context-RCA full text, before claiming novelty of the coverage gate |
