from decimal import Decimal

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


def test_session_runs_in_utc(spark: SparkSession) -> None:
    assert spark.conf.get("spark.sql.session.timeZone") == "UTC"


def test_session_keeps_decimal_amounts(spark: SparkSession) -> None:
    amounts = spark.createDataFrame(
        [("pay_A", Decimal("100.10")), ("pay_B", Decimal("0.20"))],
        "payment_id string, amount decimal(18,2)",
    )

    total = amounts.agg(F.sum("amount").alias("total")).first()

    assert total is not None
    assert total["total"] == Decimal("100.30")
