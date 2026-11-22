import pytest

from ingestion.settings import IngestionSettings, load_settings
from ingestion.topics import EVENT_TOPICS, key_for, partition_for

OTHER_EVENT_TOPICS = (
    "usage_events",
    "recharge_events",
    "package_events",
    "offer_events",
    "lifecycle_events",
    "network_events",
    "tower_metrics_events",
)


@pytest.mark.parametrize(
    "config_path",
    ("config/config.yaml", "config/config_test.yaml"),
)
def test_load_settings_from_project_configs(config_path):
    settings = load_settings(config_path, s3_root_override="raw_smoke")

    assert settings == IngestionSettings(
        bootstrap_servers="localhost:9092",
        partitions=6,
        replication=1,
        retention_ms=2_592_000_000,
        s3_bucket="churnguard-data-bilawal",
        s3_region="ap-south-1",
        s3_root="raw_smoke",
        batch_records=5000,
        batch_seconds=60,
        consumer_group="bronze-writer",
        raw_data_dir="data/raw",
        checkpoint_path="state/ingest_producer_checkpoint.json",
        producer_dlq_dir="data/dlq",
    )


def test_load_settings_uses_ingestion_overrides(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "kafka:\n"
        "  bootstrap: kafka:9092\n"
        "  retention_ms: 123\n"
        "s3:\n"
        "  prefix: raw_prefix\n"
        "ingestion:\n"
        "  retention_ms: 456\n"
        "  consumer_group: custom-group\n"
        "  raw_data_dir: custom/raw\n"
        "  checkpoint_path: state/custom.json\n"
        "  producer_dlq_dir: custom/dlq\n",
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.bootstrap_servers == "kafka:9092"
    assert settings.retention_ms == 123
    assert settings.s3_root == "raw_prefix"
    assert settings.consumer_group == "custom-group"
    assert settings.raw_data_dir == "custom/raw"
    assert settings.checkpoint_path == "state/custom.json"
    assert settings.producer_dlq_dir == "custom/dlq"


@pytest.mark.parametrize(
    ("topic", "event", "expected"),
    [
        ("customer_events", {"customer_id": "C1"}, "C1"),
        ("profile_events", {"customer_id": "C2"}, "C2"),
        ("usage_events", {"customer_id": "C3"}, "C3"),
        ("recharge_events", {"customer_id": "C4"}, "C4"),
        ("package_events", {"customer_id": "C5"}, "C5"),
        ("offer_events", {"customer_id": "C6"}, "C6"),
        ("lifecycle_events", {"customer_id": "C7"}, "C7"),
        ("network_events", {"region": "Lahore"}, "Lahore"),
        ("tower_metrics_events", {"tower_id": "T01001"}, "T01001"),
    ],
)
def test_key_for_all_event_topics(topic, event, expected):
    assert topic in EVENT_TOPICS
    assert key_for(topic, event) == expected


@pytest.mark.parametrize(
    ("topic", "key_field"),
    [
        ("customer_events", "customer_id"),
        ("profile_events", "customer_id"),
        ("usage_events", "customer_id"),
        ("recharge_events", "customer_id"),
        ("package_events", "customer_id"),
        ("offer_events", "customer_id"),
        ("lifecycle_events", "customer_id"),
        ("network_events", "region"),
        ("tower_metrics_events", "tower_id"),
    ],
)
@pytest.mark.parametrize("value", (None, ""))
def test_key_for_rejects_missing_or_empty_values(topic, key_field, value):
    with pytest.raises(ValueError):
        key_for(topic, {key_field: value})


def test_key_for_rejects_missing_field_and_unknown_topic():
    with pytest.raises(ValueError):
        key_for("customer_events", {})
    with pytest.raises(ValueError):
        key_for("unknown_events", {"customer_id": "C1"})


def test_customer_event_partition_prefers_signup_date_and_falls_back():
    assert partition_for("customer_events", {
        "signup_date": "2026-04-02",
        "event_time": "2026-05-03T00:00:00+05:00",
    }) == ("signup_month", "2026-04")
    assert partition_for("customer_events", {
        "signup_date": None,
        "event_time": "2026-05-03T00:00:00+05:00",
    }) == ("signup_month", "2026-05")
    assert partition_for("customer_events", {
        "signup_date": "invalid",
        "event_time": "2026-05-03T00:00:00+05:00",
    }) == ("signup_month", "2026-05")


def test_profile_event_partition_uses_event_time():
    assert partition_for("profile_events", {
        "event_time": "2026-04-03T00:00:00+05:00",
        "signup_date": "2026-05-03",
    }) == ("signup_month", "2026-04")


@pytest.mark.parametrize("topic", OTHER_EVENT_TOPICS)
def test_other_topic_partitions_prefer_event_date_for_late_events(topic):
    assert partition_for(topic, {
        "event_date": "2026-04-02",
        "event_time": "2026-05-03T00:00:00+05:00",
    }) == ("event_date", "2026-04-02")


@pytest.mark.parametrize("topic", OTHER_EVENT_TOPICS)
def test_other_topic_partitions_fall_back_to_event_time(topic):
    assert partition_for(topic, {
        "event_date": None,
        "event_time": "2026-05-03T00:00:00+05:00",
    }) == ("event_date", "2026-05-03")


@pytest.mark.parametrize(
    ("topic", "event"),
    [
        ("customer_events", {"signup_date": None, "event_time": "invalid"}),
        ("profile_events", {"event_time": None}),
        ("profile_events", {"event_time": "invalid"}),
        *[
            (topic, {"event_date": None, "event_time": None})
            for topic in OTHER_EVENT_TOPICS
        ],
        *[
            (topic, {"event_date": "invalid", "event_time": "invalid"})
            for topic in OTHER_EVENT_TOPICS
        ],
    ],
)
def test_partition_for_rejects_missing_or_invalid_dates(topic, event):
    with pytest.raises(ValueError, match=f"Cannot derive partition for {topic}"):
        partition_for(topic, event)


def test_partition_for_rejects_unknown_topic():
    with pytest.raises(ValueError):
        partition_for("unknown_events", {"event_date": "2026-04-01"})
