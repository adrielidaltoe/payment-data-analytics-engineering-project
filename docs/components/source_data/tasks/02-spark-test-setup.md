# Task 2: Spark test setup

**Status:** done · **PR:** [#22](https://github.com/adrielidaltoe/payment-data-analytics-engineering-project/pull/22) · [Plan](../plan.md)

Written after the task was done, when task files were introduced; it records what was built.

## Goal

Run PySpark unit tests locally and in CI, with the same Spark version as Databricks.

## Rules covered

None: this task is tooling.

## What was built

| File | Content |
| --- | --- |
| `pyproject.toml` | `pyspark==4.3.0` and `pytest-cov==7.1.0` in the dev group; pytest prints the coverage of `src/corvella` on every run |
| `tests/generator/conftest.py` | The `spark` fixture: one local SparkSession for the whole test run, `local[2]`, UTC, 2 shuffle partitions, Spark UI off |
| `tests/generator/test_spark_session.py` | The session runs in UTC; a sum of `DECIMAL(18,2)` amounts stays exact |
| `.github/workflows/ci.yml` | pytest runs with `JAVA_HOME` set to the runner's Java 17 |
| `README.md` | PySpark, Java 17 and pytest-cov in the tech stack, Java 17 in the prerequisites, how to read the coverage report |

## Decisions

- **PySpark 4.3.0 and Java 17:** serverless environment version 6, used by the bundle's jobs, runs Databricks Connect 19 (Spark 4.3) with JDK 17.
- **`local[2]`:** two threads split the data into at least two partitions, so tests catch code that depends on partitioning (SRC-C.4 requires output that doesn't), and they behave the same on every machine.
- **Two shuffle partitions:** the default of 200 makes every shuffle of a few test rows slow.
- **Coverage with no minimum:** in PySpark, a line that ran isn't a rule whose every case was tested, so a percentage target would mislead.
- **pandas 3 warning left as is:** dbt-databricks installs pandas 3, and PySpark warns that it doesn't fully support it. The generator never converts to pandas, and CI doesn't install the dbt group.

## Result

3 tests pass locally (with Java 17 installed) and in CI.
