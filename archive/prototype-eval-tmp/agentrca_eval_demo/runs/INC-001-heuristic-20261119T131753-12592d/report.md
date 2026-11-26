# RCA report - INC-001 (heuristic)

- Incident: API gateway returned 5xx errors to clients (rule `gateway-5xx`) at 2026-01-10T10:05:14Z
- Model: qwen3:8b | steps 0 | tool calls 0 | blocked 0 | wall 0.0s

## Ranked hypotheses

### 1. db-primary (confidence 0.5)
db-primary was the first component to log problems

- invalid configuration value max_connections=-1  
  evidence: E2

### 2. payment-service (confidence 0.5)
payment-service was the first component to log problems

- connection refused to db-primary:5432  
  evidence: E4

### 3. order-service (confidence 0.5)
order-service was the first component to log problems

- connection refused to payment-service:8082  
  evidence: E6

## Evidence gaps / uncertainty
- Temporal heuristic only; no causal validation.

## Recommendations (for a human operator; AgentRCA never acts)
- (none)

## Cited evidence
- [E2] `db-primary.log:29` 2026-01-10T10:04:56Z ERROR db-primary: invalid configuration value max_connections=-1
- [E4] `payment-service.log:30` 2026-01-10T10:05:02Z ERROR payment-service: connection refused to db-primary:5432
- [E6] `order-service.log:32` 2026-01-10T10:05:09Z ERROR order-service: connection refused to payment-service:8082

## Validation
- claims supported 3/3 (unsupported rate 0.0), fabricated evidence IDs 0, hypotheses dropped 0
