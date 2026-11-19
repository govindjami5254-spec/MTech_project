# RCA report - INC-001 (agent)

- Incident: API gateway returned 5xx errors to clients (rule `gateway-5xx`) at 2026-01-10T10:05:22Z
- Model: qwen3:8b | steps 8 | tool calls 7 | blocked 0 | wall 295.1s

## Ranked hypotheses

### 1. order-service (confidence 0.7)
The order-service encountered an OutOfMemoryError, leading to its process being killed by the OOM killer, which made it unavailable for the API gateway.

- The order-service experienced an OutOfMemoryError at 2026-01-10T10:05:16Z.  
  evidence: E9
- The order-service was subsequently killed by the OOM killer at 2026-01-10T10:05:18Z.  
  evidence: E14
- The API gateway returned 503 errors to clients due to the order-service being unavailable.  
  evidence: E1, E2, E3, E4, E5

## Evidence gaps / uncertainty
- There is no evidence to confirm whether the order-service's heap size was insufficient or if there was a dependency failure.
- The exact cause of the OutOfMemoryError is not specified in the logs.

## Recommendations (for a human operator; AgentRCA never acts)
- Check the heap configuration of the order-service to ensure it is sufficient for the workload.
- Investigate any potential dependency failures that may have contributed to the OutOfMemoryError.
- Monitor the order-service's memory usage and garbage collection logs to identify any patterns or issues.

## Cited evidence
- [E1] `api-gateway.log:36` 2026-01-10T10:05:22Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E2] `api-gateway.log:37` 2026-01-10T10:05:25Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E3] `api-gateway.log:38` 2026-01-10T10:05:28Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E4] `api-gateway.log:39` 2026-01-10T10:05:31Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E5] `api-gateway.log:41` 2026-01-10T10:05:34Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E9] `order-service.log:34` 2026-01-10T10:05:16Z ERROR order-service: java.lang.OutOfMemoryError: Java heap space
- [E14] `order-service.log:35` 2026-01-10T10:05:18Z FATAL order-service: process killed by OOM killer

## Validation
- claims supported 7/7 (unsupported rate 0.0), fabricated evidence IDs 0, hypotheses dropped 2
