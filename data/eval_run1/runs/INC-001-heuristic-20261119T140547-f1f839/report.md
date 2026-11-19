# RCA report - INC-001 (heuristic)

- Incident: API gateway returned 5xx errors to clients (rule `gateway-5xx`) at 2026-01-10T10:05:22Z
- Model: qwen3:8b | steps 0 | tool calls 0 | blocked 0 | wall 0.0s

## Ranked hypotheses

### 1. order-service (confidence 0.5)
order-service was the first component to log problems

- invalid configuration value max_connections=-1  
  evidence: E2

### 2. api-gateway (confidence 0.5)
api-gateway was the first component to log problems

- 503 returned to client: upstream order-service unavailable  
  evidence: E1

## Evidence gaps / uncertainty
- Temporal heuristic only; no causal validation.

## Recommendations (for a human operator; AgentRCA never acts)
- (none)

## Cited evidence
- [E1] `api-gateway.log:36` 2026-01-10T10:05:22Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E2] `order-service.log:34` 2026-01-10T10:05:16Z ERROR order-service: invalid configuration value max_connections=-1

## Validation
- claims supported 2/2 (unsupported rate 0.0), fabricated evidence IDs 0, hypotheses dropped 0
