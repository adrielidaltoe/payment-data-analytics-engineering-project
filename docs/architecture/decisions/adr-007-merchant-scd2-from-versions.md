# ADR-007: Merchant type 2 history built from preserved versions, not dbt snapshots

- **Decision:** the merchant type 2 dimension is calculated from the merchant extracts kept in bronze: silver (`stg_merchants__versions`) keeps one row per real change, and gold (`dim_merchant`) derives `valid_from`, `valid_to` and `is_current` with window functions. Both are fully rebuilt on each run. Silver also decides which attributes are type 2 (a change creates a new version) and which are type 1 (a correction, such as a typo in the legal name, updates the current value).
- **Context:** the history must be rebuildable from scratch, both for recovery and because the replay approach reruns the pipeline from the start many times. Bronze is append-only and keeps every merchant version with its change timestamp, so the history already exists there.
- **Alternatives considered:** dbt snapshots (the standard dbt pattern, but they only see the source at run time: two changes between runs lose the first, `valid_from` is the run time rather than the business time, and a lost snapshot table can't be rebuilt).
- **Consequences:** the dimension is deterministic and rebuildable; each layer still reads only from the layer below. If merchant volume crosses the 1 million row limit, the gold model becomes incremental, recalculating only merchants with new versions since the last run.

Part of the [solution design](../solution_design.md).
