# RCA report - INC-001 (single)

- Incident: API gateway returned 5xx errors to clients (rule `gateway-5xx`) at 2026-01-10T10:05:22Z
- Model: qwen3:8b | steps 0 | tool calls 0 | blocked 0 | wall 198.4s

## Ranked hypotheses

### 1. order-service (confidence 0.7)
The order-service encountered an OutOfMemoryError, leading to its process being killed by the OOM killer, which made it unavailable to the API gateway.

- The order-service ran out of memory, as indicated by the OutOfMemoryError.  
  evidence: E14
- The order-service was subsequently killed by the OOM killer, making it unavailable.  
  evidence: E19
- The API gateway reported an upstream order-service unavailable error, leading to 503 responses.  
  evidence: E1

### 2. api-gateway (confidence 0.7)
The API gateway reported an upstream service (order-service) as unavailable, but no direct evidence of gateway failure was found.

- The API gateway reported an upstream order-service unavailable error, leading to 503 responses.  
  evidence: E1
- The API gateway was handling requests normally before the incident, with no reported errors.  
  evidence: E10

## Evidence gaps / uncertainty
- No logs were found indicating the exact cause of the memory exhaustion in the order-service.
- No logs were found indicating the exact cause of the OOM killer action on the order-service.
- No logs were found indicating the exact cause of the API gateway's 503 response.

## Recommendations (for a human operator; AgentRCA never acts)
- Check the order-service's memory usage logs and configuration to determine if the heap size was appropriately set.
- Investigate the system's resource usage (CPU, memory, disk) around the incident time to identify any potential resource contention.
- Review the API gateway's upstream health checks and configurations to ensure they are correctly set up to handle service unavailability.

## Cited evidence
- [E1] `api-gateway.log:36` 2026-01-10T10:05:22Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E10] `api-gateway.log:34` 2026-01-10T10:05:09Z INFO api-gateway: request handled in 78ms status=200
- [E14] `order-service.log:34` 2026-01-10T10:05:16Z ERROR order-service: java.lang.OutOfMemoryError: Java heap space
- [E19] `order-service.log:35` 2026-01-10T10:05:18Z FATAL order-service: process killed by OOM killer

## Validation
- claims supported 5/7 (unsupported rate 0.286), fabricated evidence IDs 0, hypotheses dropped 1
