# RCA report - INC-001 (static)

- Incident: API gateway returned 5xx errors to clients (rule `gateway-5xx`) at 2026-01-10T10:05:22Z
- Model: qwen3:8b | steps 0 | tool calls 0 | blocked 0 | wall 142.1s

## Ranked hypotheses

### 1. order-service (confidence 0.7)
The order-service ran out of memory, leading to an OutOfMemoryError and subsequent termination by the OOM killer.

- The order-service experienced a Java heap space error at 2026-01-10T10:05:16Z.  
  evidence: E3
- The order-service was terminated by the OOM killer at 2026-01-10T10:05:18Z.  
  evidence: E4
- The order-service had high heap usage (92%) before the OOM error, indicating memory pressure.  
  evidence: E2

### 2. api-gateway (confidence 0.6)
The API gateway returned a 503 error to clients because the upstream order-service was unavailable.

- The API gateway returned a 503 error to clients at 2026-01-10T10:05:22Z due to the upstream order-service being unavailable.  
  evidence: E1

## Evidence gaps / uncertainty
- No evidence was found about the exact cause of the memory pressure (e.g., memory leaks, insufficient heap size, or external factors).

## Recommendations (for a human operator; AgentRCA never acts)
- Check the order-service's memory configuration and heap size to ensure it is adequate for the workload.
- Investigate if there were any memory leaks or unexpected usage patterns in the order-service.
- Monitor system-level memory usage to determine if there were broader memory constraints affecting the entire environment.

## Cited evidence
- [E1] `api-gateway.log:36` 2026-01-10T10:05:22Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E2] `order-service.log:27` 2026-01-10T10:04:16Z WARN order-service: heap usage 92% (GC overhead high)
- [E3] `order-service.log:34` 2026-01-10T10:05:16Z ERROR order-service: java.lang.OutOfMemoryError: Java heap space
- [E4] `order-service.log:35` 2026-01-10T10:05:18Z FATAL order-service: process killed by OOM killer

## Validation
- claims supported 5/5 (unsupported rate 0.0), fabricated evidence IDs 0, hypotheses dropped 1
