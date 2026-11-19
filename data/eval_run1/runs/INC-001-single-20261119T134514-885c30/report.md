# RCA report - INC-001 (single)

- Incident: API gateway returned 5xx errors to clients (rule `gateway-5xx`) at 2026-01-10T10:05:22Z
- Model: qwen3:8b | steps 0 | tool calls 0 | blocked 0 | wall 144.4s

## Ranked hypotheses

### 1. order-service (confidence 0.7)
The order-service encountered a disk space exhaustion issue, leading to a shutdown and making it unavailable for the API gateway.

- The order-service ran out of disk space on /var/lib/data, which caused it to fail writing data and eventually shut down.  
  evidence: E4, E14, E19
- The API gateway received a 503 error because the order-service was unavailable due to the storage error.  
  evidence: E1

### 2. api-gateway (confidence 0.7)
The API gateway returned 503 errors to clients because it could not reach the order-service, which had failed due to a storage issue.

- The API gateway returned a 503 error to clients because the order-service was unavailable.  
  evidence: E1
- The order-service was unavailable due to a storage error, which was the root cause of the API gateway's 503 errors.  
  evidence: E19, E14

## Evidence gaps / uncertainty
- There is no evidence indicating whether the disk space issue was resolved or if other services were affected.
- No evidence is provided about the exact time the order-service started failing or how long it was unavailable.

## Recommendations (for a human operator; AgentRCA never acts)
- Check the disk usage on /var/lib/data to ensure it is not approaching full capacity again.
- Investigate the order-service logs to determine if there were any other errors or warnings before the shutdown.
- Monitor the availability of the order-service to prevent future disruptions to the API gateway.

## Cited evidence
- [E1] `api-gateway.log:36` 2026-01-10T10:05:22Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E4] `order-service.log:32` 2026-01-10T10:04:56Z WARN order-service: disk usage 98% on /var/lib/data
- [E14] `order-service.log:35` 2026-01-10T10:05:16Z ERROR order-service: write failed: no space left on device
- [E19] `order-service.log:36` 2026-01-10T10:05:19Z FATAL order-service: shutting down: unrecoverable storage error

## Validation
- claims supported 6/6 (unsupported rate 0.0), fabricated evidence IDs 0, hypotheses dropped 1
