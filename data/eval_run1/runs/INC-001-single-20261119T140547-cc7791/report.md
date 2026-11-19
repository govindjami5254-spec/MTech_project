# RCA report - INC-001 (single)

- Incident: API gateway returned 5xx errors to clients (rule `gateway-5xx`) at 2026-01-10T10:05:22Z
- Model: qwen3:8b | steps 0 | tool calls 0 | blocked 0 | wall 282.2s

## Ranked hypotheses

### 1. order-service (confidence 0.7)
The order-service failed to apply its configuration due to an invalid max_connections value of -1, leading to an upstream failure for the API gateway.

- The order-service attempted to reload its configuration at 2026-01-10T10:05:11Z.  
  evidence: E12
- The order-service encountered an invalid configuration value max_connections=-1 at 2026-01-10T10:05:16Z.  
  evidence: E14
- The order-service exited due to the failed configuration application at 2026-01-10T10:05:18Z.  
  evidence: E19
- The API gateway returned a 503 error to the client because the order-service was unavailable at 2026-01-10T10:05:22Z.  
  evidence: E1

## Evidence gaps / uncertainty
- No evidence was found about the exact cause of the invalid max_connections value in the configuration file.

## Recommendations (for a human operator; AgentRCA never acts)
- Verify the configuration file for the order-service to ensure all values are valid before deployment.
- Implement a configuration validation step during deployment to catch invalid values before they cause service failures.
- Monitor the health of the order-service and other critical services to detect and address failures promptly.

## Cited evidence
- [E1] `api-gateway.log:36` 2026-01-10T10:05:22Z ERROR api-gateway: 503 returned to client: upstream order-service unavailable
- [E12] `order-service.log:32` 2026-01-10T10:05:11Z INFO order-service: reloading configuration from /etc/app/config.yaml
- [E14] `order-service.log:34` 2026-01-10T10:05:16Z ERROR order-service: invalid configuration value max_connections=-1
- [E19] `order-service.log:35` 2026-01-10T10:05:18Z FATAL order-service: failed to apply configuration, exiting

## Validation
- claims supported 10/10 (unsupported rate 0.0), fabricated evidence IDs 0, hypotheses dropped 2
