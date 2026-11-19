# RCA report - INC-001 (static)

- Incident: API gateway returned 5xx errors to clients (rule `gateway-5xx`) at 2026-01-10T10:05:22Z
- Model: qwen3:8b | steps 0 | tool calls 0 | blocked 0 | wall 161.7s

## Ranked hypotheses

### 1. order-service (confidence 0.7)
The order-service failed to start due to an invalid configuration value for max_connections=-1, leading to the api-gateway returning 503 errors.

- The order-service failed to start because of an invalid configuration value for max_connections=-1.  
  evidence: E2
- The order-service exited immediately after failing to apply the configuration.  
  evidence: E3
- The api-gateway returned a 503 error to the client because the upstream order-service was unavailable.  
  evidence: E1

### 2. api-gateway (confidence 0.7)
The api-gateway returned 503 errors to clients due to the upstream order-service being unavailable, which was caused by a configuration error in the order-service.

- The api-gateway returned 503 errors to clients because the upstream order-service was unavailable.  
  evidence: E1
- The order-service was unavailable due to a configuration error that caused it to exit.  
  evidence: E2, E3

## Evidence gaps / uncertainty
- No evidence was found about the source of the invalid configuration value for max_connections=-1.

## Recommendations (for a human operator; AgentRCA never acts)
- Verify the source of the configuration value for max_connections=-1 to prevent similar issues in the future.
- Implement validation for configuration values before applying them to services to avoid service failures.
- Monitor the availability of upstream services to detect and address failures promptly.

## Cited evidence
- [E1] `api-gateway.log:36` 2026-01-10T10:05:22Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E2] `order-service.log:34` 2026-01-10T10:05:16Z ERROR order-service: invalid configuration value max_connections=-1
- [E3] `order-service.log:35` 2026-01-10T10:05:18Z FATAL order-service: failed to apply configuration, exiting

## Validation
- claims supported 8/8 (unsupported rate 0.0), fabricated evidence IDs 0, hypotheses dropped 1
