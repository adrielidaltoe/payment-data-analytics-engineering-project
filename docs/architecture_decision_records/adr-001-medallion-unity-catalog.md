# ADR-001: Medallion architecture on Databricks, governed by Unity Catalog

- **Decision:** organize the data in landing, bronze, silver and gold layers, all registered in one Unity Catalog catalog.
- **Context:** the platform is fixed (Databricks with Unity Catalog), and the compliance and audit constraints require permissions, masking and lineage across all data.
- **Alternatives considered:** a single transformed layer without raw storage (simpler, but nothing can be rebuilt after a bug); separate catalogs per layer (more isolation than a project this size needs).
- **Consequences:** any layer can be rebuilt from bronze; governance is defined in one place.

Part of the [solution design](../solution_design.md).
