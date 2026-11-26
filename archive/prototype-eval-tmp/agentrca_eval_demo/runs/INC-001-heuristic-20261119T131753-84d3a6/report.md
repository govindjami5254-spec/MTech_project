# RCA report - INC-001 (heuristic)

- Incident: API gateway returned 5xx errors to clients (rule `gateway-5xx`) at 2026-01-10T10:04:51Z
- Model: qwen3:8b | steps 0 | tool calls 0 | blocked 0 | wall 0.0s

## Ranked hypotheses

### 1. cache-service (confidence 0.5)
cache-service was the first component to log problems

- slow response from backend: 850ms (p99 above threshold)  
  evidence: E2

### 2. auth-service (confidence 0.5)
auth-service was the first component to log problems

- token validation failed for user=[REDACTED_EMAIL] password=[REDACTED] (clock skew)  
  evidence: E3

### 3. order-service (confidence 0.5)
order-service was the first component to log problems

- invalid configuration value max_connections=-1  
  evidence: E4

## Evidence gaps / uncertainty
- Temporal heuristic only; no causal validation.

## Recommendations (for a human operator; AgentRCA never acts)
- (none)

## Cited evidence
- [E2] `cache-service.log:14` 2026-01-10T10:02:02Z WARN cache-service: slow response from backend: 850ms (p99 above threshold)
- [E3] `auth-service.log:18` 2026-01-10T10:02:55Z ERROR auth-service: token validation failed for user=[REDACTED_EMAIL] password=[REDACTED] (clock skew)
- [E4] `order-service.log:34` 2026-01-10T10:04:45Z ERROR order-service: invalid configuration value max_connections=-1

## Validation
- claims supported 3/3 (unsupported rate 0.0), fabricated evidence IDs 0, hypotheses dropped 0
