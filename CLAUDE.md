# CLAUDE.md

## Project

Portfolio analytics engineering project for Corvella Pay, a fictional US payment
facilitator. Focus: disputes and chargebacks. Read the relevant section of the docs before
designing anything:

- docs/business_context.md — business context, metric definitions and requirements.
- docs/architecture/ — solution design, environments and CI/CD, and the decision records (ADRs).
- docs/components/<component>/ — each component's spec.md (what it must do) and plan.md (how it is built).

## Stack (fixed — don't add tools)

- Databricks Free Edition + Unity Catalog + Asset Bundles + Databricks CLI + GitHub Actions + ruff + pytest (with pytest-cov) + sqlfluff
- dbt for all transformations
- PySpark for synthetic source data (~1% of real scale)
- Databricks AI/BI for dashboards

## Data rules

- Money: DECIMAL(18,2). Never FLOAT/DOUBLE.
- Timestamps stored in UTC; convert to US Eastern only for display.
- Never store full card numbers — only card_bin and card_last4.
- Do not guess source table schemas: always look them up in docs/components/source_data/spec.md, the single reference for source files, columns and types.
- Keep history (SCD2 / event tables); never overwrite status or merchant attributes.
- Use the metric definitions in docs/business_context.md; don't invent alternatives.
- The window to open a dispute is up to 120 days after the sale.
- Corvella automatically accepts disputes under $25.

## Code style

- Python: ruff (settings in `pyproject.toml`). SQL in dbt models: sqlfluff (settings in `dbt/.sqlfluff`): lowercase, explicit `as` aliases, trailing commas.
- Run `uv run sqlfluff fix dbt` before committing SQL. When a model uses a new package macro, add a stand-in to `dbt/sqlfluff_libs/`.
- Python design: object-oriented, following the SOLID principles.
- Use factory, builder, strategy and template method where they fit; don't add a pattern for a single variation.
- Give variables meaningful names, never single letters. The one exception is the alias `F` in `import pyspark.sql.functions as F`.
- Add type annotations to all function and method parameters and return values.
- Write a docstring for every module, class, method and function, saying what it does and, where useful, its arguments, return value and errors raised.

## Coding principles

ruff checks what it can (rule sets in `pyproject.toml`); the rest is checked in review and by tests.

- **Fail fast.** Validate inputs where they enter: parameters, seed files, expected DataFrame columns. Raise a specific exception (`ValueError`, `KeyError`, …) with a message that says what is wrong and the values involved. Never continue with data known to be wrong.
- **Never hide errors.** No bare or broad `except` (`except Exception`), and no `except: pass`. Catch only an exception you can handle, and re-raise or let it propagate otherwise.
- **Early return.** Handle special and invalid cases first with guard clauses (`if …: raise` or `return`), then write the main path without nesting. No `else` after a `return` or `raise`.
- **Each validation has a test** for the invalid case, checking the exception type and message.

## Tests

- pytest: files `test_<module>.py`, mirroring the code's folders under `tests/`.
- Group the tests of one class or function in a class named `Test<ClassName>` (for a function, its name in CamelCase: `TestAssignArrival`). No `__init__`.
- Name each test after the behavior it checks: `test_<what is tested>_<situation>_<expected result>`, in snake_case. Inside a `Test<ClassName>`, "what is tested" is the method or feature, not the class again; leave out the situation when there is only one. Example: `TestScenarioBuilder.test_build_warmup_longer_than_history_raises_error`.
- Never put rule IDs in test names. A test that checks rules starts its docstring with their IDs, then one sentence on what it checks: `"""SRC-C.4: two runs with the same parameters write identical files."""`.

## Secrets and connections

- `dbt/profiles.yml` is committed and may contain only `env_var()` references, never literal hosts, paths or tokens.
- Connection values live in `.env` (never committed); `.env.example` lists the variables with placeholders and must be kept in sync with `profiles.yml`.
- dbt does not load `.env` automatically: load it into the shell before running dbt (`set -a; source .env; set +a`).
- In CI, the same variables come from GitHub Actions secrets.
- Never print, log or hardcode tokens, even in examples or tests.

## Design principles

- Prefer simple, maintainable designs (small team).
- Synthetic data must include late arrivals, status changes and merchant changes.
- Out of scope for v1: settlement reconciliation, merchant dashboard,
  dispute prediction, fraud scoring.

## Development workflow (spec-driven)

- The user makes every decision. Claude proposes options with a recommendation and never decides alone.
- Each component (source data generator, ingestion, silver and gold dbt models, dashboards, …) has a spec (what it must do, with numbered rules) and a plan (how it is built, in small tasks), in `docs/components/<component>/spec.md` and `plan.md`. Each task has its own file, `docs/components/<component>/tasks/<NN>-<name>.md`, created when the task starts.
- Rule IDs are unique across specs, with one prefix per component (`SRC-6.7` is rule 7 of Source 6 in the source data spec).
- Before writing a task's code, Claude writes the task spec in the task's file and waits for approval. It lists the rule IDs the task covers, the classes, functions or models with their inputs and outputs, and the tests with the cases each covers. The file also records the decisions made during the task and, at the end, its result and PR.
- Every test names the rule IDs it checks, written exactly as in the spec (`SRC-C.4`): in its docstring for pytest (see Tests), in its description for dbt.
- A component is finished only when the rule coverage command (README, Checks) prints no untested rule for its prefix.
- If the code needs to differ from the spec, Claude stops and reports it as soon as it is found, before finishing the task, with the options and a recommendation.
- The spec changes only after the user approves, in the same PR as the code.

## Git workflow

- Never commit on `main`. Before committing, create a new branch and commit there.
