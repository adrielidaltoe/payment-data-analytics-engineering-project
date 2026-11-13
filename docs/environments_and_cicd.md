# Environments and CI/CD

Code reaches production in one way only: a feature branch, a pull request that passes CI, and a merge to `main` that CD deploys to the `prod` bundle target. Developers deploy to `dev` from their own machines; automation never deploys on pull requests. The decisions behind this are [ADR-008](architecture_decision_records/adr-008-jobs-as-code-asset-bundles.md) (jobs as code with Databricks Asset Bundles), [ADR-009](architecture_decision_records/adr-009-catalog-per-environment.md) (one catalog per environment).

```mermaid
flowchart LR
    dev["<b>Developer</b><br/>feature branch"] -- "bundle deploy -t dev" --> devenv["<b>dev target</b><br/>corvella_dev<br/>jobs paused"]
    dev -- pull request --> ci["<b>CI</b><br/>lint, tests, validate,<br/>dbt build on corvella_dev"]
    ci -- "passes, merge" --> main["<b>main</b>"]
    main -- push --> cd["<b>CD</b><br/>bundle deploy -t prod"]
    cd --> prodenv["<b>prod target</b><br/>corvella_prod<br/>paused until ready"]
```

## Environments

| | dev | prod |
| --- | --- | --- |
| Bundle target | `dev` | `prod`, production mode |
| Catalog | `corvella_dev` | `corvella_prod` |
| Schemas | `landing`, `bronze`, `silver`, `gold` | Same |
| Deployed by | Each developer, from their machine (`databricks bundle deploy -t dev`) | CD only, on merge to `main` |
| Job names | Prefixed with `[dev]` | Prefixed with `[prod]` |
| Schedules | Always paused, with the `trigger_pause_status: PAUSED` preset | Paused with the same preset until the pipeline is ready |
| Jobs run as | The developer | Service principal `corvella-deployer` |

**Configuration.** Everything that differs between environments is a bundle variable set per target:

- `catalog`: `corvella_dev` or `corvella_prod`. It is passed to every job, to the dbt task (`catalog: ${var.catalog}`) and to the schema and volume resources.
- `warehouse_id`: found by name with a `lookup`, as today.

**Why `dev` doesn't use development mode.** Development mode prefixes job names with the developer's name and pauses schedules, but it also prefixes every Unity Catalog schema (`dev_<user>_bronze`), and no setting turns that off for schemas alone. That would make the schemas differ between catalogs. So `dev` pauses schedules with the `trigger_pause_status` preset, and every job name starts with `[${bundle.target}]`, which tells the two environments apart in the shared workspace (ADR-009).

**Catalogs, once, with SQL.** Free Edition stores managed data in Default Storage, and the API that bundles use to create catalogs fails there. So `setup/catalogs.sql`, run once by an admin before the first deploy, creates `corvella_dev` and `corvella_prod`, grants `corvella-ci` read and write on `corvella_dev`, grants the admin read access on `corvella_prod` and then makes `corvella-deployer` its owner. The order matters: Free Edition users are workspace admins but not metastore admins, so after the owner change only the deployer could grant access. The script can be run again safely.

**Data structure as code.** `resources/catalog.yml` defines the four schemas and the landing volumes (`source_history`, `inbox`, `_checkpoints`) in `${var.catalog}`, so deploying a target creates its data structure. The `landing` schema and the `source_history` volume have `lifecycle: prevent_destroy`, so `bundle destroy` can't delete the source data.

**dbt profiles.** `profiles.yml` has two outputs. `dev`, the default, logs in with the developer's token and takes its catalog from `env_var('DBT_CATALOG', 'corvella_dev')`. `ci` logs in as `corvella-ci` with its OAuth client ID and secret and writes to `corvella_dev`; it is used only by CI (`dbt build --target ci`). dbt reads only the variables of the output it uses, so developers don't need the CI secrets. There is no prod output: only prod jobs write to `corvella_prod`. Jobs don't use `profiles.yml`; the dbt task builds its profile from the warehouse and the catalog it is given.

**Turning prod schedules on.** A pull request removes the `presets` line from the `prod` target. After the merge, CD deploys and each job follows its own schedule. A job unpaused by hand in the UI is paused again by the next deploy, so the bundle stays the single source of truth.

## Identities and secrets

Developers use their own identity; automation never uses a personal token. CI doesn't deploy, but it still logs in to Databricks to validate the bundle and to run `dbt build`, which writes tables, so it gets its own service principal with access to `corvella_dev` only. That keeps pull request code away from production credentials:

| Identity | Used by | Logs in with | Access |
| --- | --- | --- | --- |
| Each developer | Local work: `bundle deploy -t dev`, `bundle run`, dbt | Their own user (token in `.env`) | Use the SQL warehouse; read and write `corvella_dev`; the admin also reads `corvella_prod` |
| `corvella-ci` (service principal) | CI, on pull requests: `bundle validate`, `dbt build` | OAuth client ID and secret | Use the SQL warehouse; read and write `corvella_dev` |
| `corvella-deployer` (service principal) | CD, on merge to `main`; `run_as` of prod jobs | OAuth client ID and secret | Use the SQL warehouse; owns `corvella_prod` |

Each logs in with OAuth (a client ID and secret), which issues short-lived tokens automatically. Catalog access and owners are set in `setup/catalogs.sql`, so permissions are reviewed like code; schemas and tables inherit them. Warehouse access is set once by an admin.

| GitHub secret | Scope | Value |
| --- | --- | --- |
| `DATABRICKS_HOST` | Repository | Workspace URL |
| `DATABRICKS_HTTP_PATH` | Repository | SQL warehouse HTTP path, for `dbt build` in CI |
| `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` | Repository | `corvella-ci` credentials |
| `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` | GitHub environment `prod`, restricted to `main` | `corvella-deployer` credentials; only the CD workflow can read them, and they override the repository values of the same name |

## CI: on every pull request

Steps run from cheapest to most expensive; each runs only if the previous one passed.

| # | Step | Runs when |
| --- | --- | --- |
| 1 | `ruff check`, `ruff format --check` and `sqlfluff lint dbt` | Always |
| 2 | `pytest` | Always |
| 3 | `databricks bundle validate -t dev` and `-t prod` | The pull request comes from this repository (forks get no secrets) |
| 4 | `dbt deps` and `dbt build` against `corvella_dev` | Same, and the pull request changes `dbt/` |

CI does not deploy. The workflow is `.github/workflows/ci.yml`, with two jobs: `checks` (steps 1 and 2) and `databricks` (steps 3 and 4), which runs only after `checks` passes. dbt runs with the `ci` output, as `corvella-ci`, and writes to `corvella_dev`, the same catalog developers use (see ADR-009); step 4 finds `dbt/` changes with `git diff` against `main`. The workflow token is read-only, a new push cancels the run in progress, and every action is pinned to a commit SHA. uv and the Databricks CLI (installed with `databricks/setup-cli`) are pinned to the same versions as locally.

## CD: on merge to `main`

1. `databricks bundle validate -t prod`
2. `databricks bundle deploy -t prod`

The workflow runs in the GitHub environment `prod`, as `corvella-deployer`, with a `concurrency` group so two merges never deploy at the same time. The first deploy creates the schemas and volumes in `corvella_prod` and the jobs, all paused.

## Repository rules

- `main` is protected: changes go in only through pull requests, CI must pass, and force pushes are blocked. Required approvals are 0, because GitHub doesn't let authors approve their own pull requests.
- No long-lived `dev` branch: environments are bundle targets, not branches. Feature branches merge straight into `main`.
- `.env` holds local connection values and is never committed; `.env.example` lists every variable with placeholders. `profiles.yml` only reads `env_var()`.

## Folder structure

```
.
├── databricks.yml               # bundle: variables, targets (dev, prod)
├── resources/                   # bundle resources, one file per concern
│   ├── catalog.yml              #   schemas, volumes
│   ├── source_simulator.job.yml
│   ├── ingestion.job.yml
│   └── transformation.job.yml
├── setup/catalogs.sql           # one-time: catalogs, grants, owners
├── src/corvella/                # Python package, used by jobs and tests
│   ├── generator/               #   PySpark source data generator
│   ├── simulator/               #   replay into the inbox
│   └── ingestion/               #   generic Auto Loader loader and per-source config
├── dbt/                         # dbt project
├── tests/                       # pytest unit tests for src/
├── .github/workflows/
│   ├── ci.yml                   # on pull request
│   └── cd.yml                   # on push to main
├── docs/
├── pyproject.toml               # Python dependencies, ruff and pytest settings
└── .env.example, .gitignore, .python-version, README.md, CLAUDE.md
```

`pyproject.toml` replaces `requirements.txt`. The reference export of the first smoke test job moves from `databricks/jobs/` to `docs/reference/`, so no top-level `databricks/` folder sits next to `databricks.yml`.

## Implementation steps

Each step ends with a check that proves it works.

1. **Repository layout.** `pyproject.toml` (dependencies, ruff and pytest settings), an empty `src/corvella/` package, `tests/` with one test, sqlfluff for the dbt SQL (`dbt/.sqlfluff`), the reference job moved to `docs/reference/`. *Check:* `ruff check`, `sqlfluff lint dbt` and `pytest` pass locally.
2. **Service principals.** Create `corvella-ci` and `corvella-deployer` with OAuth secrets, let both use the SQL warehouse, allow `corvella-deployer` to create catalogs (no longer needed, see step 3), and add the GitHub secrets and the `prod` environment. *Check:* the CLI logs in as each one.
3. **Bundle environments.** `catalog` variable, `dev` and `prod` targets (both with the paused preset; prod in production mode, with `run_as` and `root_path` set to `corvella-deployer`), job names prefixed with the target, `setup/catalogs.sql` for the catalogs and grants from the identities table, `resources/catalog.yml` with the schemas and volumes, the smoke test job on `${var.catalog}`. *Check:* the script creates both catalogs with their grants and owners; `bundle validate -t prod` shows paused jobs run as the deployer; `bundle deploy -t dev` creates the schemas and volumes in `corvella_dev`; the smoke test job runs in dev.
4. **dbt.** `profiles.yml` catalog from `DBT_CATALOG`, `.env.example` updated. *Check:* `dbt build` locally against `corvella_dev`.
5. **CI workflow.** `.github/workflows/ci.yml`. *Check:* a test pull request runs all four steps green, as `corvella-ci`.
6. **CD workflow.** `.github/workflows/cd.yml`. *Check:* the first merge creates the schemas and volumes in `corvella_prod` and the prod jobs, paused, run as `corvella-deployer`.
7. **Branch protection.** Protect `main` and require the CI checks. *Check:* a direct push to `main` is rejected.
8. **Clean up.** Delete the smoke test job created in the UI, drop the `corvella` catalog and the empty `default` schemas that `CREATE CATALOG` adds, revoke `CREATE_CATALOG` from `corvella-deployer`, update the README (architecture, status). The `smoke_test` schema in `corvella_dev` stays while the smoke test model is the only dbt model, since CI and the dev job rebuild it; it goes, with the model and its jobs, when the first real models replace it. *Check:* only `corvella_dev` and `corvella_prod` remain, besides Free Edition's built-in `workspace` catalog.
