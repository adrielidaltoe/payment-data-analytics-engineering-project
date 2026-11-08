# ADR-005: Silver and gold built with dbt, executed by Databricks

- **Decision:** all transformations from bronze onwards are dbt models run on a Databricks SQL warehouse through the dbt-databricks adapter.
- **Context:** the team needs tested, documented, version-controlled transformations; the metrics must have one definition; Genie needs good descriptions.
- **Alternatives considered:** PySpark notebooks for all layers (flexible, but harder to test and document consistently).
- **Consequences:** tests, documentation and lineage come from dbt; descriptions are written once and pushed to Unity Catalog.

Part of the [solution design](../solution_design.md).
