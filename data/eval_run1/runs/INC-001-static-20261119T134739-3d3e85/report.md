# RCA report - INC-001 (static)

- Incident: API gateway returned 5xx errors to clients (rule `gateway-5xx`) at 2026-01-10T10:05:22Z
- Model: qwen3:8b | steps 0 | tool calls 0 | blocked 0 | wall 99.9s

## Ranked hypotheses

### 1. order-service (confidence 0.7)
The order-service ran out of disk space, causing it to become unavailable and resulting in the API gateway returning 503 errors.

- The order-service experienced disk usage reaching 98% at 10:04:56Z, which led to a write failure at 10:05:16Z.  
  evidence: E2, E3, E4
- The API gateway returned a 503 error at 10:05:22Z because the order-service was unavailable.  
  evidence: E1

### 2. api-gateway (confidence 0.7)
The API gateway returned 503 errors due to the upstream order-service being unavailable, which was caused by disk space exhaustion.

- The API gateway returned a 503 error at 10:05:22Z because the order-service was unavailable.  
  evidence: E1
- The order-service became unavailable due to disk space exhaustion, as evidenced by the write failure at 10:05:16Z.  
  evidence: E4

## Evidence gaps / uncertainty
- There is no evidence indicating whether the disk space issue was resolved or if there were any attempts to free up space.

## Recommendations (for a human operator; AgentRCA never acts)
- Check the disk usage metrics for the order-service to confirm the root cause of the disk space exhaustion.
- Verify if there were any processes or logs that could have generated excessive data leading to the disk space issue.
- Ensure that disk usage monitoring and alerting are in place to prevent similar incidents in the future.

## Cited evidence
- [E1] `api-gateway.log:36` 2026-01-10T10:05:22Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E2] `order-service.log:27` 2026-01-10T10:04:16Z WARN order-service: disk usage 91% on /var/lib/data
- [E3] `order-service.log:32` 2026-01-10T10:04:56Z WARN order-service: disk usage 98% on /var/lib/data
- [E4] `order-service.log:35` 2026-01-10T10:05:16Z ERROR order-service: write failed: no space left on device

## Validation
- claims supported 6/6 (unsupported rate 0.0), fabricated evidence IDs 0, hypotheses dropped 1
