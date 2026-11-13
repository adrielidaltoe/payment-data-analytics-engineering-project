# Corvella Pay Disputes — Solution Design

Nov 4, 2026 · Adrieli Dal'Toé

## Purpose and scope

This document describes how the disputes solution for Corvella Pay is built: the data architecture, where each layer lives, which tool processes it, and why each main decision was made. The architecture design was based on the business context and requirements presented in the [business context document](business_context.md).

The decisions are recorded as architecture decision records (ADRs): short entries with the decision, its context, the alternatives considered and the consequences. When a decision changes, a new record replaces the old one instead of rewriting history.

## Architecture overview

The solution follows a medallion architecture on Databricks, with every layer governed by Unity Catalog. Source data is generated once by a PySpark generator, then released into an inbox day by day (or hour by hour) by a replay job, so the pipeline receives data the way it would from real source systems.

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

## Layers and responsibilities

| Layer | What it holds | Load pattern | Built with |
| --- | --- | --- | --- |
| **Source history** | The full generated history of every source, each record with the time it would have arrived | Written once | PySpark generator |
| **Inbox (landing)** | Files exactly as the source systems would send them: JSON events from the gateway, networks and case system; one CSV settlement file per day; merchant extracts. Organized by source and arrival date. | One day or hour added per replay run | Replay job (PySpark) |
| **Bronze** | Raw data loaded as-is, plus load metadata (source file name, load time). Never updated or deleted. | Incremental, append-only: each run loads only new files | PySpark with Auto Loader (or COPY INTO) |
| **Silver** | Cleaned, typed and deduplicated data; disputes linked to their original payments; the dispute status history; case action events | Incremental for facts and history (payments, disputes); full rebuild only for small reference tables, following the load-pattern rule below | dbt staging and intermediate models |
| **Gold** | The dimensional model: merchant dimension (type 2), reason code and date dimensions; payment facts; dispute accumulating snapshot; daily snapshots of the open queue and of merchant balances; metric definitions | Same as silver | dbt marts and semantic layer or metric views |
| **Consumption** | Work queue, dashboards, Genie space, SQL access | Read-only | Databricks AI/BI |

Each layer has one job. Bronze keeps what the sources said, unchanged, so any later layer can be rebuilt from it. Silver applies the business rules for cleaning and linking. Gold shapes the data for the questions and metrics in the business context.

**Load patterns, defined:**

- **Full rebuild:** every run reads all the rows of the model's inputs and replaces the whole target table (in dbt, the `table` materialization, which runs `CREATE OR REPLACE TABLE`).
- **Incremental load:** every run reads only the input rows that are new or changed since the last run, using a watermark such as the ingestion timestamp, and writes only those to the target. Rows that never change are appended; rows that change over time are upserted with `MERGE` on their key (in dbt, the `incremental` materialization).

**Load-pattern rule for silver and gold models.** A model is fully rebuilt only when, at Corvella Pay's full scale, it holds fewer than **1 million rows** over its 7-year retention; every other model is loaded incrementally. The rule uses full-scale volumes, not the project's 1% sample, so the design stays valid in production.

With the volumes from the business context:

| Model | Rows at full scale over 7 years | Load pattern | What runs in Databricks | Why |
| --- | --- | --- | --- | --- |
| Payments | About 1.3 billion | Incremental, append | `INSERT INTO` with only the new events, deduplicated on the event ID (dbt incremental, `append`) | Payment events never change; only new ones arrive, so writing just the new rows is the cheapest option |
| Disputes (accumulating snapshot) | About 5.8 million | Incremental, `MERGE` on the dispute ID for every dispute with a new event since the last run | `MERGE INTO … ON dispute_id` (dbt incremental, `merge`) | The disputes that change are scattered across months, so no date range captures them; matching on the key is the natural fit, and the table is small enough that Delta's file rewrites stay cheap |
| Dispute status history and case actions | Several times the number of disputes | Incremental, append | `INSERT INTO` with only the new events, deduplicated on the event ID (dbt incremental, `append`) | Each status change or action is a new row that is never updated |
| Daily snapshots (open queue, balances) | One set of rows per day | Incremental, replace one day per run | `INSERT INTO … REPLACE WHERE snapshot_date = <run date>` (dbt incremental, `replace_where`) | Rerunning a day replaces that day instead of duplicating it, so reruns are safe (idempotent) and the day matches the source exactly |
| Merchant versions (silver, `stg_merchants__versions`) | About 0.8 million (40,000 merchants plus their changes) | Full rebuild from the merchant extracts in bronze | `CREATE OR REPLACE TABLE … AS SELECT` that keeps a row only when a tracked attribute (risk tier, segment, category, reserve rate, status) differs from the merchant's previous version, using `LAG()` (dbt `table`) | Bronze keeps every extract it receives, so the versions can be recalculated exactly at any time; repeated rows for unchanged merchants are collapsed into real changes. Assumption about the source: the onboarding system sends a change extract each day (only merchants created or changed that day), which keeps bronze near 0.8 million rows. If it sent a full extract of all merchants every day instead, bronze would hold about 100 million merchant rows over 7 years, and this model would have to become incremental, processing only the newest extract. |
| Merchant dimension (gold, `dim_merchant`, type 2) | About 0.8 million | Full rebuild from the silver versions | `CREATE OR REPLACE TABLE … AS SELECT` with `LEAD()` over each merchant's versions to set `valid_from`, `valid_to` and `is_current`, plus a surrogate key and an unknown-merchant row (dbt `table`) | The full history can be rebuilt from scratch at any time, which dbt snapshots can't do; `valid_from` is the business change time, not the run time (see [ADR-007](architecture_decision_records/adr-007-merchant-scd2-from-versions.md)) |
| Reference data (reason codes, categories, thresholds) | Hundreds | Full rebuild | `CREATE OR REPLACE TABLE … AS SELECT` (dbt `table`) | A few hundred rows: rebuilding costs almost nothing and needs no incremental logic |

Incremental models keep a full-refresh option (`dbt run --full-refresh`) for when a business rule changes and history must be recalculated from bronze.

## Source data

The generator produces one set of files per source system, each with its own format and delivery schedule. The replay job releases them into the inbox exactly as those systems would send them.

| # | Source system | Inbox folder | Format and cadence | What it contains | Key columns |
| --- | --- | --- | --- | --- | --- |
| 1 | Payment gateway | `gateway_events` | JSON, hourly | One event stream for authorizations, captures, refunds and voids, distinguished by `event_type` | event_id, event_type, event_ts, payment_id, merchant_id, amount, currency, channel, card_brand, card_type, card_bin, card_last4, mcc, status, response_code, risk_score |
| 2 | Acquirer | `settlement_files` | CSV, once per business day | One line per settled sale, refund or adjustment | file_name, line_number, settlement_date, acquirer_reference, payment_id, transaction_type, gross_amount, interchange_fee, network_fee, acquirer_fee, net_amount |
| 3 | Card networks | `dispute_notifications` | JSON, several times a day | One event per dispute stage: chargeback opened, second round opened, arbitration, outcome won or lost | notification_id, dispute_id, acquirer_reference, network, notification_type, reason_code, amount, respond_by, received_ts |
| 4 | Card networks | `early_alerts` | JSON, several times a day | Alerts before a chargeback, and their outcome (refunded or expired) | alert_id, acquirer_reference, network, alert_type, amount, alert_ts |
| 5 | Case system | `case_actions` | JSON, hourly | One event per action on a case | action_id, dispute_id, action_type (case_opened, merchant_notified, evidence_received, evidence_submitted, merchant_accepted, auto_accepted), action_ts, actor |
| 6 | Onboarding and risk system | `merchants` | JSON, daily change extract (only merchants created or changed that day) | Merchant attributes | merchant_id, legal_name, mcc, segment, risk_tier, reserve_rate, status, account_manager_id, contact_email, onboarding_date, updated_at |
| 7 | Internal ledger | `merchant_balances` | CSV, daily | End-of-day balance and reserve per merchant | balance_date, merchant_id, available_balance, reserve_balance |

**Reference data** (reason codes, merchant categories and policy thresholds) is not generated as source files. It is kept as dbt seeds: CSV files versioned in the Git repository, each row with an effective date, because people maintain this data (Risk sets the thresholds, the networks publish the codes) and its changes should go through code review.

**Design choices:**

- **Dispute notifications and resolutions are one event stream.** Networks send a sequence of notices about the same dispute; storing them as events gives the dispute status history directly.
- **Disputes arrive without Corvella Pay's `payment_id`.** Networks identify the transaction by its `acquirer_reference`, so silver matches each dispute to its payment through the settlement lines. This is the linking problem behind the 99.5% accuracy requirement.
- **Payouts are not generated.** The disputes solution only needs balances and reserves; payouts can be added if reconciliation becomes a project.

**Behaviors the generator must build in**, so the data carries the problems from the business context:

- **Late arrivals:** disputes arrive 1 to 120 days after the sale, mostly in the first 30 to 60 days; settlement lines arrive 1 to 2 business days after capture.
- **Status changes over months:** some disputes go through a second round.
- **The business problem:** a portfolio dispute rate rising from about 0.31% to 0.46%, a few merchants trending toward the 0.75% and 1.5% lines, and about 18% of disputes expiring.
- **Merchant changes:** risk tiers and reserve rates change over time, so the type 2 dimension has real history.
- **Data quality traps:** duplicate events, a few disputes whose acquirer reference matches no payment, and settlement adjustments, so the dbt tests have something to catch.

**Volume at 1% scale:** about 400 merchants, 5,000 payments a day and 20 to 25 disputes a day, over 24 months of history.

## Unity Catalog organization

Each environment has its own catalog, `corvella_dev` and `corvella_prod`, with the same schemas, one per layer ([ADR-009](architecture_decision_records/adr-009-catalog-per-environment.md)):

```
corvella_dev / corvella_prod (catalog)
├── landing   volumes: source_history, inbox, _checkpoints
├── bronze    raw tables, loaded by PySpark
├── silver    cleaned and linked tables, built by dbt
└── gold      dimensional model and metrics, built by dbt
```

The inbox volume is organized by source and arrival date:

```
/Volumes/<catalog>/landing/inbox/
    gateway_events/arrival_date=2026-10-14/
    settlement_files/arrival_date=2026-10-16/
    dispute_notifications/arrival_date=2026-12-02/
    case_actions/arrival_date=2026-12-02/
    merchants/arrival_date=2026-12-02/
```

At a real company, the sources would write to cloud storage (for example an S3 bucket) registered as an external volume. In Databricks Free Edition there is no own cloud storage, so the project uses managed volumes; the design is otherwise the same.

Unity Catalog provides, across all layers: permissions by role, column masks and row filters (the compliance constraints), lineage from file to dashboard (the audit constraint), and table and column descriptions, which dbt writes from its documentation and which the Genie space reads.

## Processing and orchestration

**Who does what.** PySpark processes the data from the generator up to bronze. From bronze onwards, transformations are written in dbt, but dbt does not process data itself: it compiles each model into SQL (`CREATE OR REPLACE TABLE`, or `MERGE` for incremental models), runs the models in dependency order, and sends the SQL through the dbt-databricks adapter to a Databricks SQL warehouse, which executes it. The results are Delta tables in Unity Catalog.

**Where dbt runs.** During development, from the local machine. In continuous integration, from GitHub Actions on every pull request. On schedule, as a **dbt task in the transformation job**, which is triggered when the ingestion job finishes (see "Job layout"). The job is defined in the Databricks Asset Bundle (see [ADR-008](architecture_decision_records/adr-008-jobs-as-code-asset-bundles.md)), so the dbt task runs the copy of the project that `databricks bundle deploy` uploads to the workspace. It runs dbt Core on serverless jobs compute and sends the generated SQL to the workspace's serverless SQL warehouse; the run date is passed to dbt as a variable (for example `--vars '{"run_date": "{{job.start_time.iso_date}}"}'`).

**Smoke test for the dbt task.** Before the pipeline relies on a dbt task, a minimal test confirms it works in Free Edition. The main risk is network access: Free Edition restricts outbound internet access to trusted domains, and it is not documented whether GitHub, PyPI and the dbt package hub are among them.

*Setup:*

- A minimal dbt project in the GitHub repository: `dbt_project.yml`, a `packages.yml` with one package (`dbt_utils`), and one model, `smoke_test`, that creates a one-row table.
- A Databricks Job with one dbt task: source **Git provider** (the GitHub repository, `main` branch), **serverless** compute, an environment with a pinned `dbt-databricks` version, the workspace's serverless SQL warehouse, catalog `corvella`, schema `smoke_test`.
- dbt commands, in order: `dbt deps`, `dbt debug`, `dbt run --select smoke_test`.

*Pass criteria, and what each failure means:*

| Check | Passes when | If it fails |
| --- | --- | --- |
| GitHub access | The task clones the repository | Sync the repository into a Databricks Git folder and use the Workspace source; if that also fails, use the GitHub Actions fallback |
| PyPI access | `dbt-databricks` installs in the task environment | Use the GitHub Actions fallback |
| dbt package hub access | `dbt deps` downloads `dbt_utils` | Commit the packages to the repository, or avoid external packages |
| Warehouse connection | `dbt debug` reports the connection OK | Check the warehouse selection and the Run As user's permission to use it |
| Unity Catalog write | `dbt run` creates `corvella.smoke_test.smoke_test` | Grant `USE CATALOG`, `USE SCHEMA` and `CREATE TABLE` on the target schema |

If every check passes, the dbt task is confirmed for scheduled runs.

**Result (Nov 9, 2026): passed.** A job with one dbt task, reading `main` from GitHub on serverless compute with `dbt-databricks` 1.13.0, ran `dbt deps`, `dbt debug` and `dbt run --select smoke_test`, and all five checks passed. The task used the profile Databricks generates from the selected SQL warehouse, not the committed `profiles.yml`, so no token is stored in the job. Scheduled dbt runs use the dbt task; the GitHub Actions fallback is not needed. The job definition is kept for reference in [`docs/reference/dbt-smoke-test.json`](reference/dbt-smoke-test.json) (exported from the Jobs API). To reuse it, replace `<your-sql-warehouse-id>` with your SQL warehouse ID (the last part of its HTTP path) and `git_url` with your copy of the repository; in Databricks Asset Bundles these become variables.

**Bundle deploy (Nov 9, 2026): passed.** The same job, defined in the Databricks Asset Bundle (`databricks.yml` and `resources/dbt_smoke_test.job.yml`), was validated, deployed to the `dev` target and run with Databricks CLI 1.22.1. The warehouse was found by name through a bundle variable, the job was created as `[dev <user>] dbt-smoke-test`, the task ran the project files uploaded by the deploy (not a Git clone), and the run rebuilt `corvella.smoke_test.smoke_test`. Only files tracked by Git are uploaded, so `.env` stays local. Jobs are therefore defined as code with bundles (see [ADR-008](architecture_decision_records/adr-008-jobs-as-code-asset-bundles.md)).

**Schedules**, following the latency requirements:

| Run | Frequency | What it does |
| --- | --- | --- |
| Queue run | Hourly, 8:00 to 20:00 US Eastern time | Replay releases the next hour of dispute notifications and case actions; bronze loads them; dbt rebuilds the dispute models and the work queue |
| Daily run | Once a day, finishing before 8:00 | Replay releases the previous day for all sources; bronze loads everything new; dbt builds all silver and gold models, including the daily snapshots and the merchant dimension |

In the project, the replay job also plays the role of the clock: one run advances the simulated time by one hour or one day. That makes it possible to run several simulated days in a row to show history building up.

**Run modes.** At 1% scale, 24 months of history is about 12 million rows, around 1 GB in Delta, which a 2X-Small warehouse handles easily. Free Edition does not publish its daily compute quota, and exceeding it shuts down compute for the rest of the day, so the replay does not run all 24 months day by day (that would be thousands of job runs). It has two modes instead, using the same jobs:

| Mode | What it does | When |
| --- | --- | --- |
| **Backfill** | The generator produces 24 months for all seven sources. The first 23 months are released into the inbox in 23 batches, one per month, oldest first; each batch holds every file whose arrival date falls in that month. Each batch goes through the normal jobs: the source simulator releases the month, then the ingestion job and the transformation job run exactly as on any day. No separate backfill code exists: the same pipeline just handles a bigger batch. | Once at the start, and again after a full rebuild |
| **Demo replay** | Advances the simulated clock day by day (or hour by hour for the work queue, for one or two simulated days) over the last 14 to 30 days, on demand, with an "advance N days" parameter instead of a real-time schedule. Runs in sessions of a few simulated days at a time, spread across real days, to stay well within the daily compute quota. | When demonstrating incremental loads, late arrivals and history building up |

The generator also produces the history month by month, so each generation step stays small. If the quota is ever hit, the scale drops to 0.5% or the history to 12 months; only the generator parameters change.

**Job layout.** The pipeline is split into three independent jobs, so a failure in one source or step doesn't block the rest:

```mermaid
---
title: "Three jobs: a failing source never blocks the others"
---
flowchart LR
    sim["<b>Source simulator</b><br/>replay: drops files by<br/>source and period<br/><i>not part of the solution</i>"] -- files --> ing["<b>Ingestion job</b><br/>one task per source,<br/>up to 5 at once<br/>each fails and retries alone"]
    ing -- bronze --> tr["<b>Transformation job</b><br/>dbt source freshness,<br/>then dbt build<br/>silver and gold"]
```

| Job | What it does | How it runs |
| --- | --- | --- |
| **Source simulator** | The replay: drops files into the inbox for the requested sources and period. It stands in for the external systems and is not part of the solution. | Parameters: `sources` (default all) and `period` (an hour, a day or a month) |
| **Ingestion** | Loads new inbox files into bronze. One generic notebook, parameterized by source name and driven by a small config per source (format, inbox path, target table), run with a "For each" task over the source list. | Concurrency 5, Free Edition's limit; each source loads, fails and retries independently |
| **Transformation** | Runs dbt: first `dbt source freshness`, which stops the run if a source is not up to date, then `dbt build` for silver and gold | Triggered when the ingestion job finishes |

The hourly path is the same layout with `sources` set to dispute notifications and case actions, and only the dbt models that use them. Each job allows one active run at a time, and the daily run is scheduled outside the hourly window.

## Architecture decision records

Each decision is recorded in its own file:

| ADR | Decision |
| --- | --- |
| [ADR-001](architecture_decision_records/adr-001-medallion-unity-catalog.md) | Medallion architecture on Databricks, governed by Unity Catalog |
| [ADR-002](architecture_decision_records/adr-002-generate-once-replay.md) | Generate the source data once, then replay it by arrival time |
| [ADR-003](architecture_decision_records/adr-003-landing-uc-volume.md) | Landing in a Unity Catalog volume |
| [ADR-004](architecture_decision_records/adr-004-bronze-append-only.md) | Bronze is append-only, loaded incrementally by PySpark |
| [ADR-005](architecture_decision_records/adr-005-dbt-silver-gold.md) | Silver and gold built with dbt, executed by Databricks |
| [ADR-006](architecture_decision_records/adr-006-batch-processing.md) | Batch processing, no streaming |
| [ADR-007](architecture_decision_records/adr-007-merchant-scd2-from-versions.md) | Merchant type 2 history built from preserved versions, not dbt snapshots |
| [ADR-008](architecture_decision_records/adr-008-jobs-as-code-asset-bundles.md) | Jobs defined as code with Databricks Asset Bundles |
| [ADR-009](architecture_decision_records/adr-009-catalog-per-environment.md) | One catalog per environment, deployed as bundle targets |
| [ADR-010](architecture_decision_records/adr-010-service-principals.md) | Automation and prod jobs run as service principals |
| [ADR-011](architecture_decision_records/adr-011-single-repository.md) | One repository for pipeline code and dbt |
