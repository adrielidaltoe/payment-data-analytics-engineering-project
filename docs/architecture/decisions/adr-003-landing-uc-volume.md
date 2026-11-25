# ADR-003: Landing in a Unity Catalog volume

- **Decision:** the inbox and source history are managed volumes in the `landing` schema of each environment's catalog (`corvella_dev`, `corvella_prod`; see ADR-009).
- **Context:** Databricks Free Edition has no own cloud storage; volumes keep files governed like tables.
- **Alternatives considered:** an external cloud bucket (the real-company setup, but needs a cloud account); writing straight to tables (skips file ingestion, which is part of what the project should show).
- **Consequences:** moving to a real bucket later only changes the volume type, not the pipeline.

Part of the [solution design](../solution_design.md).
