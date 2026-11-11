# Corvella Pay — Disputes & Chargebacks Analytics

An end-to-end analytics engineering project on **Databricks** and **dbt**, built around a realistic fintech problem: managing card payment disputes (chargebacks) at a payment facilitator.

Corvella Pay is a fictional US payment facilitator serving about 40,000 small and mid-sized merchants. All company data is synthetic, generated with PySpark to reproduce the behavior of real payment sources: late-arriving disputes, status changes over months, and merchants whose attributes change over time.

## The business problem

Disputes cost Corvella Pay money and put its relationship with its acquiring bank at risk:

- The portfolio dispute rate rose from 0.31% to 0.46% in a year, close to Visa's 0.50% line for an acquirer's portfolio. The acquirer has asked for an action plan.
- About 18% of disputes are lost because the response deadline passes before evidence is submitted.
- Risky merchants are found weeks late, in a monthly spreadsheet.
- Unrecovered dispute losses reached $1.9 million last year.
- Risk, Finance and Disputes Operations each report a different dispute rate.

The root cause is data: dispute information is scattered across systems, arrives late, overwrites its own history and has no single metric definitions.

## What the solution delivers

| Consumer | Delivers | Freshness |
| --- | --- | --- |
| Disputes Operations | Work queue of open disputes, sorted by deadline and amount | Hourly, business hours |
| Risk | Dispute rates per merchant and portfolio, watch list, reserve coverage | Daily |
| Finance and leadership | Dispute losses, open exposure, cohort dispute rates, acquirer report | Daily and month-end |
| Everyone | Governed metrics and a Genie space for plain-language questions | Same as the tables |

## Architecture

```mermaid
---
title: Data is generated once, then replayed as if the sources sent it live
---
flowchart LR
    gen["<b>Generator</b><br/>PySpark: full history, once"] --> hist["<b>Source history</b><br/>volume: all data<br/>+ arrival times"]
    hist --> replay["<b>Replay job</b><br/>releases one day<br/>or hour per run"]
    replay -- copies new arrivals --> inbox["<b>Inbox</b><br/>volume: files<br/>as sources send"]
    inbox --> bronze["<b>Bronze</b><br/>raw, append-only<br/>PySpark ingest"]
    bronze --> silver["<b>Silver</b><br/>clean, linked<br/>dbt models"]
    silver --> gold["<b>Gold</b><br/>dimensional model<br/>+ metrics"]
    gold --> consumption["<b>Consumption</b><br/>dashboards,<br/>queue, Genie"]
```

- **Medallion architecture** in one Unity Catalog catalog (`corvella`), with schemas `landing`, `bronze`, `silver` and `gold`.
- **Generate once, replay by arrival time:** the full history is generated once, then released into the inbox day by day (or hour by hour), so the pipeline receives data the way it would from real source systems.
- **Bronze** is append-only, loaded incrementally by Auto Loader with an `availableNow` trigger.
- **Silver and gold** are dbt models executed on a Databricks SQL warehouse. Gold is a dimensional model: payment facts, a dispute accumulating snapshot, a type 2 merchant dimension and daily snapshots.
- **Three jobs:** source simulator, ingestion (one task per source) and transformation (dbt), so a failing source never blocks the others.
- **Batch, not streaming:** no decision needs data fresher than one hour.

## Key decisions

| ADR | Decision |
| --- | --- |
| [001](docs/architecture_decision_records/adr-001-medallion-unity-catalog.md) | Medallion architecture on Databricks, governed by Unity Catalog |
| [002](docs/architecture_decision_records/adr-002-generate-once-replay.md) | Generate source data once, replay it by arrival time |
| [003](docs/architecture_decision_records/adr-003-landing-uc-volume.md) | Landing in a Unity Catalog volume |
| [004](docs/architecture_decision_records/adr-004-bronze-append-only.md) | Bronze append-only, loaded by Auto Loader (`availableNow`) |
| [005](docs/architecture_decision_records/adr-005-dbt-silver-gold.md) | Silver and gold built with dbt, executed by Databricks |
| [006](docs/architecture_decision_records/adr-006-batch-processing.md) | Batch processing, no streaming |
| [007](docs/architecture_decision_records/adr-007-merchant-scd2-from-versions.md) | Merchant type 2 history built from preserved versions, not dbt snapshots |
| [008](docs/architecture_decision_records/adr-008-jobs-as-code-asset-bundles.md) | Jobs defined as code with Databricks Asset Bundles |
| [009](docs/architecture_decision_records/adr-009-catalog-per-environment.md) | One catalog per environment, deployed as bundle targets |
| [010](docs/architecture_decision_records/adr-010-service-principals.md) | Automation and prod jobs run as service principals |

## Tech stack

Databricks Free Edition (serverless compute, Unity Catalog, Jobs, AI/BI dashboards, Genie) · PySpark · dbt Core with dbt-databricks · GitHub Actions

| Tool | Version | Where it is set |
| --- | --- | --- |
| Python | 3.12 (same as Databricks serverless jobs) | `.python-version` |
| dbt Core | 1.12 | Installed with dbt-databricks |
| dbt-databricks | 1.13.0 | `pyproject.toml` (`dbt` group) |
| ruff | 0.17.3 | `pyproject.toml` (`dev` group) |
| pytest | 9.2.0 | `pyproject.toml` (`dev` group) |
| Databricks CLI | 1.22.1 | Installed separately (see How to run) |

## How to run

Prerequisites:

- [uv](https://docs.astral.sh/uv/), used to create the Python environment. The project uses Python 3.12, the version Databricks serverless jobs run; uv downloads it if it is missing, without changing the system Python.
- [Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install), used to deploy the jobs defined in `databricks.yml` and `resources/` (Databricks Asset Bundles).

1. Create the virtual environment and install the project with its tools (dbt, ruff, pytest); versions are pinned in `pyproject.toml` and locked in `uv.lock`:

    ```bash
    uv sync
    source .venv/bin/activate
    ```

2. Copy `.env.example` to `.env` and fill in your Databricks workspace host, SQL warehouse HTTP path and personal access token. `.env` is ignored by Git and must never be committed.

    ```bash
    cp .env.example .env
    ```

3. Load the variables into your shell, then run dbt from the `dbt/` folder, where the project and its `profiles.yml` live. dbt does not read `.env` by itself, so the variables must be exported before running any dbt command:

    ```bash
    set -a; source .env; set +a   # export everything in .env
    cd dbt
    dbt deps    # install dbt packages
    dbt debug   # check the connection to the SQL warehouse
    ```

4. Deploy and run the jobs with the Databricks CLI, from the repository root, in the same shell (the CLI reads the same variables from `.env`). The `dev` target prefixes every job with `[dev <your user>]`, so it does not clash with other people's jobs:

    ```bash
    databricks bundle validate                   # check the bundle files
    databricks bundle deploy -t dev              # upload the code and create or update the jobs
    databricks bundle run -t dev dbt_smoke_test  # run a job
    ```

### Checks

Lint and unit tests run locally without Databricks (CI runs the same commands):

```bash
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run pytest                # unit tests
```

## Project status

Done:

- [x] Business context and requirements
- [x] Solution design and architecture decisions
- [x] Smoke test for the dbt task in a Databricks Job
- [x] Databricks Asset Bundles: smoke test job deployed and run from the bundle

Next:

- [ ] Repository, environments (dev and prod) and CI/CD with Asset Bundles ([plan](docs/environments_and_cicd.md))
- [ ] Source data generation: detailed spec and generator
- [ ] Schema for each layer and the gold dimensional model
- [ ] Semantic layer and metric definitions
- [ ] Ingestion and dbt models, with data quality tests and contracts
- [ ] Governance and security: permissions, masks, row filters
- [ ] Consumption: work queue, Risk dashboard, Genie space
- [ ] Data monitoring
- [ ] Documentation and portfolio packaging

## Documentation

- [Business context](docs/business_context.md) — company, payment lifecycle, dispute process, business questions, metrics, requirements and constraints.
- [Solution design](docs/solution_design.md) — architecture, layers, source data, Unity Catalog layout, processing and orchestration.
- [Environments and CI/CD](docs/environments_and_cicd.md) — dev and prod targets, identities and secrets, CI and CD workflows, repository rules and implementation steps.
- [Architecture decision records](docs/architecture_decision_records/) — one file per architecture decision (ADR-001 to ADR-010).
