"""Shared fixtures for the generator tests."""

from collections.abc import Iterator

import pytest
from pyspark.sql import SparkSession


@pytest.fixture(scope="session")
def spark() -> Iterator[SparkSession]:
    """Start one local SparkSession for the whole test run.

    The session runs in UTC, like the generated data, and uses few shuffle
    partitions because test DataFrames have only a handful of rows.
    """
    session = (
        SparkSession.builder.master("local[2]")
        .appName("corvella-generator-tests")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()
