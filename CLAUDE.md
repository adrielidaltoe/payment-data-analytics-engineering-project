# CLAUDE.md

## Project

Portfolio analytics engineering project for Corvella Pay, a fictional US payment
facilitator. Focus: disputes and chargebacks. Full business context, source schemas,
metric definitions and requirements are in docs/business_context.md — read the relevant section
before designing models or metrics.

## Stack (fixed — don't add tools)

- Databricks Free Edition + Unity Catalog
- dbt for all transformations
- PySpark for synthetic source data (~1% of real scale)
- Databricks AI/BI for dashboards

## Data rules

- Money: DECIMAL(18,2). Never FLOAT/DOUBLE.
- Timestamps stored in UTC; convert to US Eastern only for display.
- Never store full card numbers — only card_bin and card_last4.
- Source column names follow the "Data produced at each stage" tables in docs/business_context.md.
- Keep history (SCD2 / event tables); never overwrite status or merchant attributes.
- Use the metric definitions in docs/business_context.md; don't invent alternatives.

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

## Git workflow

- Never commit on `main`. Before committing, create a new branch and commit there.
