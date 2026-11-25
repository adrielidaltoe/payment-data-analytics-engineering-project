from decimal import Decimal

from pyspark.sql import SparkSession
from pyspark.sql import functions as F


class TestSpark:
    """Tests of the `spark` fixture in conftest.py."""

    def test_session_time_zone_is_utc(self, spark: SparkSession) -> None:
        assert spark.conf.get("spark.sql.session.timeZone") == "UTC"

    def test_sum_of_decimal_amounts_stays_exact(self, spark: SparkSession) -> None:
        amounts = spark.createDataFrame(
            [("pay_A", Decimal("100.10")), ("pay_B", Decimal("0.20"))],
            "payment_id string, amount decimal(18,2)",
        )

        total = amounts.agg(F.sum("amount").alias("total")).first()

        assert total is not None
        assert total["total"] == Decimal("100.30")
