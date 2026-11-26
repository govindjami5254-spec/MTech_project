# RCA report - INC-001 (agent)

- Incident: API gateway returned 5xx errors to clients (rule `gateway-5xx`) at 2026-01-10T10:04:51Z
- Model: qwen3:8b | steps 1 | tool calls 0 | blocked 0 | wall 0.0s

## Ranked hypotheses
_None passed validation._

## Evidence gaps / uncertainty
- Component 'cache-service' logged problems from 2026-01-10T10:02:02Z (before the incident) but was not inspected.
- Component 'auth-service' logged problems from 2026-01-10T10:02:55Z (before the incident) but was not inspected.
- Component 'order-service' logged problems from 2026-01-10T10:04:45Z (before the incident) but was not inspected.
- Investigation stopped early: llm_error.
- The model did not return a valid analysis.
- No hypothesis passed evidence-grounding validation.

## Recommendations (for a human operator; AgentRCA never acts)
- (none)

## Cited evidence

## Validation
- claims supported 0/0 (unsupported rate 0.0), fabricated evidence IDs 0, hypotheses dropped 0
