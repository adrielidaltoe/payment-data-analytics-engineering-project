# Task 1: Seeds

**Status:** done · **PR:** [#21](https://github.com/adrielidaltoe/payment-data-analytics-engineering-project/pull/21) · [Plan](../plan.md)

Written after the task was done, when task files were introduced; it records what was built.

## Goal

The reference data that both the generator and dbt use, as dbt seeds.

## Rules covered

- **SRC-R.1 Seeds shared with dbt.**

## What was built

| File | Content |
| --- | --- |
| `dbt/seeds/reason_codes.csv` | 20 real reason codes, 10 Visa and 10 Mastercard, across the five reason categories; all valid from 2020-01-01, no end date |
| `dbt/seeds/merchant_categories.csv` | 20 real MCCs, 5 per segment (5651 is `ecommerce`, as in the spec's example) |
| `dbt/seeds/policy_thresholds.csv` | The five thresholds from the spec, valid from 2020-01-01 |
| `dbt/seeds/_seeds.yml` | Column types for every column (so codes like `13.1` and MCCs stay text) and 18 data tests: not null, unique, accepted values, unique code and date pairs |
| `dbt/macros/generate_schema_name.sql` | Uses a custom schema name as written (`silver`) instead of dbt's default `<target schema>_<custom schema>` |
| `dbt/dbt_project.yml` | Seeds go to the `silver` schema |

## Decisions

- **Seeds in `silver`:** the data is already clean and typed, and the gold dimensions are built from it. Bronze is for raw data loaded by PySpark.
- **`policy_thresholds.value` is `DECIMAL(18,4)`:** the one `value` column holds rates (0.0075) as well as dollar amounts (25.00).
- **No code or threshold changes over the window:** the spec defines none, so every row stays valid for the whole history.

## Result

- `dbt build --select resource_type:seed` in `corvella_dev`: `PASS=21` (3 seeds, 18 tests). CI passed.
- The first run failed with "Cannot create the resource" when opening the connection: the SQL warehouse can't start until you have logged in to the workspace that day.

## Pending

- The 18 seed tests don't name SRC-R.1 in their descriptions yet; the convention came after this task. Until they do, the rule coverage command lists SRC-R.1 as untested.
