# ADR-006: Batch processing, no streaming

- **Decision:** hourly runs for the work queue during business hours, daily runs for everything else.
- **Context:** deadlines are measured in days; no decision needs data fresher than one hour; the compute budget is limited.
- **Alternatives considered:** streaming with Structured Streaming (fresher data, but more cost and complexity with no business benefit).
- **Consequences:** simple, cheaper jobs; if a future use needs minutes-level freshness, the hourly path can move to streaming without changing the model.

Part of the [solution design](../solution_design.md).
