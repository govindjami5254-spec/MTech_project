# RCA report - INC-001 (rule)

- Incident: API gateway returned 5xx errors to clients (rule `gateway-5xx`) at 2026-01-10T10:05:05Z
- Model: qwen3:8b | steps 0 | tool calls 0 | blocked 0 | wall 0.0s

## Ranked hypotheses

### 1. api-gateway (confidence 0.5)
Upstream dependency unavailable

- 503 returned to client: upstream order-service unavailable  
  evidence: E1

## Evidence gaps / uncertainty
- Rule-based detection only; no dependency analysis.

## Recommendations (for a human operator; AgentRCA never acts)
- (none)

## Cited evidence
- [E1] `api-gateway.log:32` 2026-01-10T10:05:05Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable

## Validation
- claims supported 1/1 (unsupported rate 0.0), fabricated evidence IDs 0, hypotheses dropped 0
