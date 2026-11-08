# ADR-002: Generate the source data once, then replay it by arrival time

- **Decision:** a PySpark generator creates the full history once, with an arrival time on every record; a replay job releases one day or hour at a time into the inbox.
- **Context:** the requirements depend on incremental loads, late-arriving disputes, status changes over months and type 2 merchant history. Fully static tables would show none of that and would leave the ingestion jobs out of the project.
- **Alternatives considered:** static tables (simplest, but no incremental behavior); generating new data on every run (realistic, but results are not reproducible).
- **Consequences:** runs are reproducible and can be replayed from the start; the generator must produce realistic arrival delays.

Part of the [solution design](../solution_design.md).
