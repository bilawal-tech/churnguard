import pytest

pytest.importorskip("pyspark")

from pyspark.sql import functions as F

from silver.spark_session import build_spark
from silver.tables.facts import build_offers, build_subscriptions, impute_offers, impute_package
from silver.tables.usage import derive_usage


@pytest.fixture(scope="module")
def spark():
    s = build_spark("test-silver-facts", master_override="local[2]", shuffle_partitions_override=2)
    yield s
    s.stop()


def test_derive_usage(spark):
    df = spark.createDataFrame(
        [("2026-04-01T13:00:00+05:00", 2, 1, 0, 3, 1.0, 2.0, None, 0.5, 0.5, 0, 1.5, 2.5)],
        "t string, calls_onnet_min int, calls_offnet_min int, calls_intl_min int, sms_count int, "
        "data_mb_whatsapp double, data_mb_social double, data_mb_video double, data_mb_browsing double, "
        "data_mb_other double, dropped_calls int, spend_from_package double, spend_from_balance double",
    ).withColumn("event_time", F.to_timestamp("t"))
    r = derive_usage(df).collect()[0]
    assert r["band"] == "Afternoon"
    assert r["total_call_min"] == 3
    assert r["total_data_mb"] == 4.0
    assert r["total_spend"] == 4.0
    assert r["has_null_measure"] is True


def test_impute_package(spark):
    df = spark.createDataFrame([("P1", None), ("P9", 7), (None, None)], "package_id string, validity_days int")
    dim = spark.createDataFrame([("P1", 30)], "package_id string, validity_days int")
    rows = {r["package_id"]: r for r in impute_package(df, dim).collect()}
    assert rows["P1"]["validity_days"] == 30 and rows["P1"]["validity_days_imputed"] is True
    assert rows["P9"]["package_known"] is False and rows[None]["package_known"] is None


def test_impute_offers_rule_and_discount(spark):
    df = spark.createDataFrame(
        [("O1", "DATA_BOOST", None, 0.25), ("O1", "DATA_BOOST", "usage_mix", None), ("O2", "CRICKET_PACK", None, None)],
        "offer_id string, offer_type string, trigger_rule string, discount_pct double",
    )
    rows = impute_offers(df).collect()
    o1 = [r for r in rows if r["offer_id"] == "O1"]
    assert all(r["discount_pct"] == 0.25 for r in o1)
    assert {r["trigger_rule"] for r in rows if r["offer_id"] == "O2"} == {"event"}


def test_build_offers_final_action(spark):
    df = spark.createDataFrame(
        [
            ("O1", "C1", "SENT", "2026-05-01"), ("O1", "C1", "ACCEPTED", "2026-05-02"),
            ("O2", "C2", "SENT", "2026-05-01"),
            ("O3", "C3", "HELD", "2026-05-01"),
            ("O4", "C4", "SENT", "2026-05-01"), ("O4", "C4", "EXPIRED", "2026-05-08"),
        ],
        "offer_id string, customer_id string, action string, d string",
    ).withColumn("event_date", F.to_date("d"))
    for c in ["offer_type", "group", "trigger_rule", "campaign_name", "package_id"]:
        df = df.withColumn(c, F.lit("x"))
    df = df.withColumn("discount_pct", F.lit(None).cast("double"))
    got = {r["offer_id"]: r["final_action"] for r in build_offers(df).collect()}
    assert got == {"O1": "ACCEPTED", "O2": "OPEN", "O3": "HELD", "O4": "EXPIRED"}


def test_build_subscriptions(spark):
    df = spark.createDataFrame(
        [("S1", "C1", "P1", "PURCHASE", "2026-05-01T00:00:00+05:00"),
         ("S1", "C1", "P1", "AUTO_RENEW", "2026-05-08T00:00:00+05:00"),
         ("S1", "C1", "P1", "EXPIRE", "2026-05-15T00:00:00+05:00")],
        "subscription_id string, customer_id string, package_id string, action string, t string",
    ).withColumn("event_time", F.to_timestamp("t"))
    r = build_subscriptions(df).collect()[0]
    assert r["n_renewals"] == 1 and r["expired"] is True and r["auto_renew_off"] is False