# LogAgent-RCA — Literature Review (verification notes)

Status: working notes, 2026-11-19. Part A (20) papers were each read in full text once (one reviewer
pass); quotations are verbatim from `pdftotext` output, page numbers are PDF page indices and may
be approximate for two-column layouts. Part B items are **abstract-level only** and must not be
cited as verified until read in full.

Gap elements used throughout:
(i) iterative agent vs. single-pass LLM with the same available evidence **and** a matched token
budget; (ii) small locally hosted models (≤14B); (iii) log-only RCA; (iv) code-level enforcement
of exploration coverage; (v) in-pipeline validator rejecting claims unsupported by cited evidence;
(vi) adversarial safety testing (prompt injection via logs, unauthorised tool calls).

Search coverage: arXiv API (2 rounds), Crossref (IEEE member 263, ACM member 320), OpenAlex,
Semantic Scholar (mostly rate-limited: 4 of 19 queries answered). DBLP returned bot-check pages;
IEEE Xplore and ACM DL APIs returned 403; Google Scholar blocks automated access. **A manual
Google Scholar / IEEE Xplore / ACM DL search is still required** (Section C).

---

## A. Full-text verified papers

### A1. RCACopilot — arXiv 2305.15778
- **Status:** EuroSys '24, DOI 10.1145/3627703.3629553.
- **Method:** Alert-type handlers (OCE-built decision-tree workflows) collect diagnostics; GPT-4
  summarises, then few-shot CoT predicts a root-cause category. Non-agentic.
  "The decision-making process… resembles a decision tree's control flow" (§4.1.1).
- **Data:** Private; "a one-year dataset of 653 incidents from Microsoft's Transport service" (§5.1, p10).
  Multi-source: "error logs, exception stack traces, and socket metrics" (§4.1.3, p7).
- **Findings:** "micro F1-score of 0.766 and a macro F1-score of 0.533" (§5.3). The abstract's
  "accuracy up to 0.766" is micro-F1. Inference ≈4.2 s (Table 2, p11).
- **Limitations:** "only integrated with OpenAI's GPT models" (§6); single service; label quality.
- **Gap elements:** i N, ii N, iii N, iv N, v N, vi N.
- **Relevance:** Pipeline baseline lineage for E2b; not a competitor on our gap.

### A2. RCAgent — arXiv 2310.16340
- **Status:** CIKM '24, DOI 10.1145/3627673.3680016.
- **Method:** ReAct-style controller agent with LLM "expert agents" as tools.
  "Vicuna-13B-V1.5-16K… with vLLM… on a single NVIDIA A100" (§4.1, p5).
- **Data:** Private Alibaba Flink jobs: "15,616 anomalous jobs" → 161-job offline set (§4.2.1, p5);
  logs plus advisor history DB and code repositories (§4.2.2).
- **Findings:** Beats ReAct (Tables 1–5). Online, beats an "LLM Summary" baseline that received
  "all possible types of relevant data… truncated if exceeding the model length constraint" (§6.1, p7).
  Tukey HSD p = 0.001 vs. ReAct (§6.1). "While utilizing more data and consuming more resources…" (§6.2).
- **Mechanisms relevant to us:** soft warning for "early finalizing without thorough investigation"
  (§3.3.2, p4) — criteria unstated; log-expert evidence filter: "If the evidence listed by LLMs cannot
  be fuzzy-matched to the chunk p, the analysis result is discarded" (§3.2.2).
- **Limitations:** No limitations section; "trading off the model's ability for security" (§2).
- **Gap elements:** i P (unmatched budget, truncated baseline), ii Y, iii P, iv P (soft), v P
  (sub-agent level only), vi N.
- **Relevance:** **Nearest prior art for the coverage gate and the validator.** Must be cited and
  distinguished.

### A3. Exploring LLM-based Agents for RCA (Roy et al.) — arXiv 2403.04123
- **Status:** FSE '24 Companion, DOI 10.1145/3663529.3663841.
- **Method:** ReAct (GPT-4-8k) vs. retrieval and CoT baselines; budget "for parity" is document
  count: "maintaining an overall budget of 10 retrieved documents" (§3.4, p5). Agent also gets raw
  description access via a QA tool (evidence asymmetry).
- **Data:** Private Microsoft incidents, 500 test incidents (§5.1).
- **Findings:** "competitive correctness rates (35% for ReAct S+Q BM25 vs 39% for the baselines)";
  hallucination "4% for ReAct vs 12% for CoT and 40% for RB (k=10)" (p7). Single run, no tests.
- **Gap elements:** i P (document cap, not tokens), ii N, iii N, iv N, v N, vi N.
- **Relevance:** Supports H2 direction (fewer hallucinations) without accuracy gain.

### A4. MicroRCA-Agent — arXiv 2509.15635
- **Status:** arXiv preprint (CCF AIOps Challenge 2025 technical report).
- **Method:** Fixed pipeline despite the name: Drain + filtering for logs, Isolation Forest for
  traces, two LLM calls; "only used for phenomenon summary… does not perform fault judgment" (§3.4.1, p9).
  LLM not named.
- **Findings:** Modality ablation (Table 1, p16): Log 23.59, Trace 31.09, Metric 42.78, L+M 51.27,
  all 50.71. Reported hallucinated reasoning in a bad case (§4.1, p16).
- **Gap elements:** i N, ii N, iii P (ablation only), iv N, v N, vi N.
- **Relevance:** Evidence of a **log-only ceiling** on public multimodal data.

### A5. Stalled, Biased, and Confused — arXiv 2601.22208
- **Status:** FORGE '26, DOI 10.1145/3793655.3793732. Code: github.com/boerste/rca-llm-reasoning.
- **Method:** ReAct, Plan-and-Execute, Straight-Shot (single pass) on GAIA and OpenRCA Market.
  Straight-Shot: "receives all alerts and system knowledge upfront and returns a diagnosis in a single
  pass" (§3.2.1, p4). Agents access the same KG via tools. No token budget matching.
- **Models:** Llama 3.2 3B, Qwen3 4B/32B, Llama 3.3 70B, Command R+ 104B; "run locally" (§3.4.3, p6).
- **Findings:** "Agentic workflows show diminishing or negative returns on LA, TA, and HA" (Obs. 2, p6).
  Qwen3-4B "explored the KG with tools in only 23.4% of ReAct samples" (Obs. 4, p7). Plan-and-Execute
  failure 87.3% (Qwen3-4B). Agents +40% / +354% inference time (§A.6.2). Authors recommend "evidence
  sufficiency checks, temporal ordering validators, and KG-consistency filters" (Obs. 10, p8).
- **Limitations:** Alerts "not gold-labeled and may contain noise" (§5, p8); multimodal input.
- **Gap elements:** i P, ii P, iii N, iv N (measured, not enforced), v N (recommended), vi N.
- **Relevance:** **Closest prior work.** Predicts that small-model agents may not beat single pass;
  motivates testing whether controller enforcement changes this.

### A6. Why Do AI Agents Systematically Fail at Cloud RCA? — arXiv 2602.09937
- **Status:** arXiv preprint (6 pages).
- **Method:** Process-level failure analysis of OpenRCA's controller–executor agent; 5 API models,
  "1,675 agent runs" (Abstract) = 335 × 5, one run per task.
- **Findings:** Hallucination in Interpretation 1193 (71.2%), Incomplete Exploration 1071 (63.9%)
  (Table 3, p3); all models >66% and >53% respectively (§4.1, p4). Prompting: "Neither produced a
  meaningful improvement in root cause identification" (§5.1, p5). Cost: "609.9 hours… 1.38 billion
  tokens… $1,394" (§3, p2).
- **Limitations:** Bank-subset mitigations; semi-automated classification (§6, p6). Internal count
  inconsistencies (Table 3 denominators; Bank subset 70 vs. 41).
- **Gap elements:** all N. Future work: "verification modules that cross-check agent interpretations
  against raw data" (§6).
- **Relevance:** Motivates coverage gate and validator as code-level (not prompt-level) fixes.

### A7. LogJack — arXiv 2604.15368
- **Status:** arXiv preprint. Payloads: github.com/HarshShah1997/logjack (LICENSE: MIT, verified).
- **Method:** 42 payload entries in cloud logs against shell-capable debugging agents; commands are
  intercepted, "without execution" (§V.A, p2). Read-only agents out of scope: "our results represent
  an upper bound" (§III, p2).
- **Findings:** Llama 3.3 70B hijack 86.2% (95% CI [79.9, 91.2], n = 160, Table II, p4); input
  guardrails detected 0–1 of 32 (Table VI). Diagnosis manipulation not scored.
- **Data note:** `metadata.total_payloads` = 37 conflicts with 42 entries; 10 benign controls.
- **Gap elements:** vi Y; others N.
- **Relevance:** Reusable payloads (adapt AWS commands); controls usable for false-block rate.

### A8. Poisoning the Watchtower — arXiv 2605.24421
- **Status:** arXiv preprint.
- **Method:** Tool-less LLM analyst (gpt-4o-mini, temp 0): "We do not assume that the LLM can execute
  commands, call tools…" (§2, p2). Four injection classes S1–S4.
- **Findings:** Mean injection success 26.6% naive → 11.8% constrained (§5.4, p5); S3 summarisation
  96% naive (Table 2, p6). No false-positive figures.
- **Gap elements:** vi Y (decision manipulation, not RCA); others N.
- **Relevance:** Shows log text steers conclusions; we test this against RCA ground truth with tools.

### A9. Auditable Graph-Guided RCA for Kubernetes — arXiv 2606.08590
- **Status:** arXiv preprint.
- **Method:** LangGraph traversal with "fixed read-only tool allow-list" (§IV-C, p3); validator
  "applies deterministic checks… and rejects classifications that fail them" (§IV-D, p3).
  qwen-flash via DashScope API.
- **Findings:** F1 0.6087 → 0.9130 (n = 23); "most of the aggregate gain is prompt-tuned" (p5);
  "the validator accepted a false checkout root cause" (§VIII-B, p6); true node "still unvisited in the
  traversal queue" (p6). Single runs (§IX).
- **Gap elements:** v P, vi P (read-only design, no adversarial tests); others N.
- **Relevance:** Prior art for deterministic grounding; shows existence checks alone are insufficient
  and bounded traversal is not coverage.

### A10. OpenRCA 2.0 — arXiv 2606.27154
- **Status:** arXiv preprint; data "released publicly" "Upon acceptance", CC-BY-SA 4.0 (A.6, p13).
- **Method:** ReAct agents, 11 API models, temp 0.7, "hard cap of 100" tool calls (F.2, p22).
- **Findings:** 20.7% exact set, 76.0% any correct service, 61.5% path reachability (recomputed from
  Table 2). Logs-only not evaluated; "The current release does not define train/development/test
  splits" (A.2, p12). Evidence SQL re-executed by judge; "whether the rows actually back the claim is
  not scored here" (G.2.2, p28).
- **Gap elements:** v P (evaluation-time only); others N.
- **Relevance:** Motivates grounded-diagnosis metric; not usable as data yet.

### A11. Log-Insight — arXiv 2607.08529
- **Status:** arXiv preprint (ASE '26 per paper header; no DOI found in Crossref).
- **Method:** Log-only six-stage symbolic pipeline → "Forensic Case File" (46,000-character budget) →
  enterprise LLM "accessed as a service" (§4.1, p4).
- **Findings:** MRR 0.790 ± 0.287 (Table 2); mean latency 27 s (§4.2); 11 private incidents, 110 runs.
  ">90% top-3" stated but per-rank distribution not reported. "1,000–7,000×" ratio undefined.
- **Limitations:** No agentic or RAG baseline (§5.3); evidence accuracy not measured (§6).
- **Gap elements:** iii Y; others N.
- **Relevance:** Template for our strong single-pass baseline E2b.

### A12. How Far Can RCA Go on Real-World Telemetry? — arXiv 2607.13548
- **Status:** arXiv preprint.
- **Method:** GPT-5.2 pipeline variants on OpenRCA. "Every Stage 1 arm receives the same evidence
  interface" (§3.1, p4), but "The OpenRCA agent is not input-matched to the others" (p7).
- **Findings:** Mined rules raise CB2 score 14.10 → 35.90 (Holm-significant, Table 2). "Every score is
  also a single run" (p9); tokens not captured (p27).
- **Gap elements:** iv P (prompted), v P (prompted self-check); others N.
- **Relevance:** Methodological precedent for fixing evidence offline across arms.

### A13. AgentRCA (industrial sensors) — arXiv 2607.22385
- **Status:** arXiv preprint (EPFL).
- **Method:** Tool-augmented agent + autoencoder "digital twin" on PRONTO and TEP sensor data;
  Qwen3-30B-A3B on vLLM; "maximum of 10 tool-call iterations" (§4.1, p14).
- **Findings:** Hypothesis table best (Top-1 87.6, Fig. 4A); grounding prompt-only (§3, p11).
- **Gap elements:** ii P; others N.
- **Relevance:** **Name clash** (reason for internal name LogAgent-RCA); different domain.

### A14. Loom — arXiv 2609.02649
- **Status:** EMNLP 2026 Industry, DOI 10.18653/2026.emnlp-industry.53 (per OpenAlex; not IEEE/ACM).
- **Method:** Deterministic heuristics → consensus → one LLM call; vs. RCA-Agent (~62 calls).
  Loom LLM sees only denoised hypotheses (§3.3, p3) — evidence differs.
- **Findings:** Bank strict 38.97 vs. 40.44 (agent); Telecom 29.41 vs. 41.18; ~26× / ~33× speed-ups
  hold on Bank only (566.8 s vs. ~22 s / ~17 s). Llama-3.1-8B on Bank 35.29.
- **Gap elements:** i P, ii P; others N.
- **Relevance:** Single-pass competitive at much lower latency — supports our RQ3 framing.

### A15. EviRCA — arXiv 2609.19825
- **Status:** arXiv preprint. Code: github.com/yuhao541/EviRCA.
- **Method:** Deterministic evidence cards + LLM with 8 read-only tools; partly iterative: Fig. 2
  example has 5 tool steps; call counts not stated.
- **Findings:** Correct 43.9% (deepseek-v4-pro) / 40.6% (qwen3.7-plus) (§IV-B). Single-call Oracle
  Sampling (15.2%) beat iterative RCA-Agent (13.4%) (Table III), but with different evidence.
  "Instability" claimed without repeated runs.
- **Gap elements:** v P (submit_answer validation, unspecified); others N.
- **Relevance:** Strongest argument against our hypothesis; its evidence does not isolate iteration.

### A16. Does Graph Structure Earn Its Place? — arXiv 2609.27069
- **Status:** Preprint (Zenodo/arXiv). No LLM; metrics only.
- **Findings:** Prior-only ranker "AC@5 0.997" in-distribution, collapses to Avg@5 0.192 across
  systems (§5.1–5.2, p7). Twelve-item checklist (§9, p13–14), including "Compute significance over
  independent folds, never over repeated measurements" and "Write the decision rule down before you
  have the result".
- **Relevance:** Basis for our floor baseline, case-level statistics and pre-registration.

### A17. Fault-Free Profiles… via Small Language Models — arXiv 2611.02416
- **Status:** arXiv preprint.
- **Method:** Qwen3-4B fine-tuned with LoRA + DPO, single call, vLLM; multimodal.
- **Findings:** Bank 48.7 vs. 18.5 for OpsAgent (authors' result files, not re-run). Same input:
  fine-tuned 4B 33% vs. off-the-shelf 14B 26% (§5.5, p16).
- **Gap elements:** i P, ii P (fine-tuned); others N.
- **Relevance:** Shows small models can be strong, but via training — outside our zero-shot scope.

### A18. Where Does the Accuracy of LLM-Based RCA Come From? (Hussain & Farrukh)
- **Status:** Research Square preprint, DOI 10.21203/rs.3.rs-11401166/v1, posted 2026-10-19, not peer
  reviewed; authors "developed the system under study" (p1).
- **Method:** One single-call agent on RCAEval RE2 (270) and RE3 (90), multimodal; text conditions
  (stripped, decoy, placebo, nolog, …) with the same detector output (§4.4, p12); 2×2 of evidence × prompt.
  Models gpt-oss-120b/20b, qwen3.8-27b via Groq, temp 0.1 (§4.5, p15).
- **Findings:** RE2 AC@1 0.441 vs. N-Sigma 0.800 (Table 4, p20); RE3 0.600 → 0.356 without log text
  (H6a, p27); evidence effect +0.296 vs. prompt +0.051 (Table 12, p31); decoy named first in 21–42%
  (Table 5) and 62% in the generic pipeline (p30).
- **Statistics:** pre-registered; "95% cluster-bootstrap interval… two-sided cluster sign-flip permutation
  test (10,000 permutations)" (§4.7, p16), Holm; most conditions run once (§7, p37).
- **Limitations:** "We study one single-call agent… agents that call tools, iterate or retrieve may behave
  differently" (§7, p36).
- **Gap elements:** i N, ii P (open-weight 20–120B, hosted), iii N, iv N, v N, vi P (decoy steering only).
- **Relevance:** Precedent for our statistical protocol (D-020) and diagnosis-steering metric; shows logs
  carry much of RE3's signal; explicitly leaves iterative agents open.

### A19. Free to Look, Free to Reason (Bi et al.) — arXiv 2610.35767
- **Status:** arXiv preprint (v1, 2026-10-26).
- **Method:** One-shot, SQL agent (≤100 calls) and Codex harnesses vs. five published agents on RCAtlas
  (90 cases from eight public datasets, all with metrics; Table 1, p4). Same information "namely the
  flagged period, the candidate inventory and the telemetry" (§5, p3), but one-shot evidence is
  rule-selected (§6.3, p7); shared limit is wall-clock time, not tokens (prompt tokens 235k–381k, Table 8).
- **Findings:** PR@1 Codex 77.2, SQL agent 72.8, one-shot 65.3 vs. FoA 53.3 (Table 3, p6). Published
  agents with more prescribed calls scored lower, but "measures how much of an investigation is fixed,
  not that this fixing causes the lower accuracy" (p8).
- **Statistics:** three runs for some arms; paired bootstrap over cases (App. B).
- **Gap elements:** i P, ii N, iii N, iv N (coverage measured, and authors argue against prescribed steps),
  v N (IDs cited, not validated), vi N.
- **Relevance:** **Counter-argument to the coverage gate** — prescribing investigation may hurt; A2 must
  test this. Also: free agents beat one-shot here with frontier models, contrary to 2601.22208 for small models.

### A20. TriFleetRCA — arXiv 2609.23766
- **Status:** arXiv preprint (v1, 2026-09-20).
- **Method:** Single pass, no tools: fixed-scope evidence (Loki pod logs + Kubernetes API state), template
  de-duplication, BM25 top-25 lines, one call to Qwen2.5-14B-Instruct on local vLLM (§IV, §V.A).
  "No external service was contacted" (p4).
- **Findings:** Hit 0.85–0.95; grounded-citation rate 0.75; dns-blocked grounding 0/5 even when correct;
  median 1.6 s, ~2,200 prompt tokens. Citations resolved to lines but only graded offline by regex
  (§V.E). Poisoned runbook rejected by pattern guard in 80/80; guard off 0/20 followed (§VI.C);
  no false-block test.
- **Gap elements:** i N, ii Y, iii N (logs + K8s state), iv N, v P, vi P.
- **Relevance:** Shows a ≤14B local single-pass pipeline is practical and fast — a realistic E2b design
  point; no agent comparison.

---

## B. Discovered beyond arXiv — abstract level only (NOT verified)

Update 2026-11-19: three ★ items were read in full and moved to A18–A20. The three IEEE ★ items
(Context-RCA, RCAgentOps, VerifyRCA) are listed as CC-BY open access, but IEEE Xplore blocked automated
download (HTTP 418); they remain **abstract-level** until downloaded manually in a browser.

Must be read in full before the gap is finalised. Items marked ★ could affect our novelty claims.

| Item | Venue / ID | Possible overlap |
|---|---|---|
| ★ Context-RCA | IEEE JointCloud 2026, DOI 10.1109/jcc72984.2026.00052 | (iv) SOP workflow blocks conclusions until enough evidence |
| ★ RCAgentOps | IEEE AIoTC 2026, DOI 10.1109/aiotc71250.2026.11689122 | (iv) rule-based coverage checks in critic; (v) evidence records |
| ★ VerifyRCA | IEEE ICETIS 2026, DOI 10.1109/icetis70504.2026.11633469 | (v) non-LLM verifier; fixed query budget |
| VerifyOps | IEEE MLISE 2026, DOI 10.1109/mlise70044.2026.11607508 | (v); noise robustness |
| HERO | ASE 2026, DOI 10.1145/3832783.3837509 | (i) partly: workflow vs. ReAct vs. hypothesis-centred agents |
| Cloud-OpsBench | arXiv 2603.00468 | (iv) measures "evidence closure" |
| Beyond Fault Localization | arXiv 2608.21310 | (iv)/(v) trajectory analysis of omitted/unsupported evidence |
| When AIOps Become "AI Oops" | arXiv 2508.06394 | (vi) telemetry injection against AIOps agents |
| Hiding Prompt Injections in Their Own Logs | Zenodo 10.5281/zenodo.23808719 | (vi), (ii) 8–20B open-weight; attack classification task |
| Silent Egress | IEEE EIT 2026, DOI 10.1109/eit68936.2026.11670372 | (vi), (ii) local qwen2.5:7b |
| AetherLog | ISSRE 2025, DOI 10.1109/issre66568.2025.00019 | (iii) log-based RCA + KG |
| OpenStack-RCA-Bench | ASE 2026, DOI 10.1145/3832783.3834650 | **Dataset:** 64 incidents, log-only, injection ground truth |
| LLM AIOps in air-gapped systems | EuroMLSys 2026, DOI 10.1145/3805621.3807626 | (ii), (iii) |
| Log-To-Leak | arXiv 2610.36108 | (vi) via MCP tool metadata |
| Surveys | ACM CSUR 10.1145/3746635; TOSEM 10.1145/3842759 (LLM4Log); arXiv 2406.11213 | Coverage check |

Many 2026 IEEE items are from lower-tier conferences; treat their results as unreviewed claims.

**Original OpenRCA (ICLR 2025):** proceedings page
https://proceedings.iclr.cc/paper_files/paper/2025/hash/d29b8d53678015079e1d245c023e49d2-Abstract-Conference.html
(no DOI or arXiv ID; OpenReview returned 403 to automated access).

**Publication status updates:** RCAEval → WWW '25 Companion, DOI 10.1145/3701716.3715290;
Flow-of-Action → 10.1145/3701716.3715225; OpsAgent → ASE 2026, 10.1145/3832783.3834479;
GALA+ → ASE 2026, 10.1145/3832783.3834335; LogConfigLocalizer (2404.00640) → ISSTA 2024,
10.1145/3650212.3652106; LATS-RCA → Springer LNCS, 10.1007/978-3-032-36590-3_14.

---

## C. Outstanding before the gap is final

1. Full-text read of Context-RCA, RCAgentOps and VerifyRCA (download manually; CC-BY on IEEE Xplore).
   Priority: Context-RCA (abstract claims it prevents "premature conclusions before sufficient evidence is collected").
2. Manual searches in Google Scholar, IEEE Xplore and ACM DL (automated access blocked), using:
   `"root cause" LLM agent logs`, `"root cause" "single-pass" OR "one-shot" LLM agent`,
   `"prompt injection" logs agent operations`, `"small language model" "root cause"`,
   `LLM agent "evidence" verification incident diagnosis`. Record date, database, hit count.
3. DBLP venue scans (ICSE, FSE, ASE, ISSRE, DSN, SoCC, EuroSys) once DBLP access works.
