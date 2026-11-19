# RCA report - INC-001 (agent)

- Incident: API gateway returned 5xx errors to clients (rule `gateway-5xx`) at 2026-01-10T10:05:22Z
- Model: qwen3:8b | steps 8 | tool calls 8 | blocked 0 | wall 352.4s

## Ranked hypotheses

### 1. order-service (confidence 0.7)
The order-service encountered a disk space exhaustion issue, leading to a shutdown and making it unavailable to the API gateway.

- The order-service ran out of disk space, causing it to shut down.  
  evidence: E9, E14
- The API gateway started returning 503 errors because the order-service was unavailable.  
  evidence: E1, E2, E3, E4, E5

## Evidence gaps / uncertainty
- There is no evidence indicating whether the disk space issue was due to a specific process or data accumulation.
- No logs indicate whether the disk space was manually managed or if there was a configuration issue.

## Recommendations (for a human operator; AgentRCA never acts)
- Check the disk usage on /var/lib/data to confirm if it was indeed full and if there are any processes using excessive space.
- Review the order-service logs to determine if there was a specific operation or data type that caused the disk to fill up.
- Ensure that the storage system for the order-service has sufficient capacity and is monitored for disk usage to prevent future outages.

## Cited evidence
- [E1] `api-gateway.log:36` 2026-01-10T10:05:22Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E2] `api-gateway.log:37` 2026-01-10T10:05:25Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E3] `api-gateway.log:38` 2026-01-10T10:05:28Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E4] `api-gateway.log:39` 2026-01-10T10:05:31Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E5] `api-gateway.log:41` 2026-01-10T10:05:34Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E9] `order-service.log:35` 2026-01-10T10:05:16Z ERROR order-service: write failed: no space left on device
- [E14] `order-service.log:36` 2026-01-10T10:05:19Z FATAL order-service: shutting down: unrecoverable storage error

## Validation
- claims supported 6/6 (unsupported rate 0.0), fabricated evidence IDs 0, hypotheses dropped 2
