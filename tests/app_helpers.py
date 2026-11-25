"""Shared helpers for application (CLI/web) tests: a deterministic scripted LLM and dev-case inputs.

No test in the application suite contacts Ollama.
"""
import json
import re
from pathlib import Path

from logagent_rca.llm import LLMResponse, ScriptedLLM, ToolCall

ROOT = Path(__file__).resolve().parent.parent
DEV_CASE = ROOT / "data" / "synthetic" / "dev" / "cases" / "dev-c004"     # easy dev case (no ground truth used)


def dev_inputs(case_dir: Path = DEV_CASE) -> dict:
    man = json.loads((case_dir / "incident.json").read_text())
    inc = man["incident"]
    src, line = inc["trigger_uid"].rsplit(":", 1)
    return {"files": [(f, (case_dir / f).read_bytes()) for f in man["log_files"]],
            "incident_id": inc["id"], "description": inc["description"], "timestamp": inc["ts"],
            "trigger_file": src, "trigger_line": int(line), "trigger_component": inc["trigger_component"],
            "rule_id": inc["rule_id"]}


def scripted_llm() -> ScriptedLLM:
    """E3: two tool calls then DONE. Final: cite the earliest ERROR line in the conversation."""
    def script(messages, tools, schema):
        text = "\n".join(m.get("content") or "" for m in messages)
        if schema:
            hits = re.findall(r"\[(E\d+)\] \S+ (?:ERROR|FATAL) (\S+) \(\S+\) (.*)", text)
            if not hits:
                return LLMResponse(content=json.dumps({"insufficient_evidence": True, "hypotheses": [],
                                                       "evidence_gaps": ["no errors seen"], "recommendations": []}))
            eid, comp, msg = hits[0]
            return LLMResponse(content=json.dumps({"insufficient_evidence": False, "hypotheses": [{
                "cause_component": comp, "cause_summary": f"{comp} failed", "confidence": 0.7,
                "claims": [{"text": f"{comp} {msg}"[:150], "evidence_ids": [eid]},
                           {"text": "unrelated claim about certificates expiring", "evidence_ids": ["E99"]}]}],
                "evidence_gaps": [], "recommendations": [f"Check {comp} health."]}),
                prompt_tokens=120, output_tokens=40)
        n = sum(1 for m in messages if m["role"] == "tool")
        if n == 0:
            return LLMResponse(tool_calls=[ToolCall("error_timeline", {})], prompt_tokens=80, output_tokens=8)
        if n == 1:
            return LLMResponse(tool_calls=[ToolCall("search_logs", {"min_severity": "ERROR", "limit": 5})],
                               prompt_tokens=90, output_tokens=8)
        return LLMResponse(content="DONE", prompt_tokens=100, output_tokens=1)
    return ScriptedLLM(script)
