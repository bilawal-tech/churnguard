"""Create missing Kafka event topics without changing existing topics."""
import argparse

from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

from ingestion.settings import IngestionSettings, load_settings
from ingestion.topics import EVENT_TOPICS


def ensure_topics(
    settings: IngestionSettings, admin_client=None
) -> dict[str, list[str]]:
    owns_client = admin_client is None
    if owns_client:
        admin_client = KafkaAdminClient(
            bootstrap_servers=settings.bootstrap_servers
        )

    existing = []
    created = []
    try:
        known_topics = set(admin_client.list_topics())
        for topic in EVENT_TOPICS:
            if topic in known_topics:
                existing.append(topic)
                continue

            new_topic = NewTopic(
                name=topic,
                num_partitions=settings.partitions,
                replication_factor=settings.replication,
                topic_configs={"retention.ms": str(settings.retention_ms)},
            )
            try:
                futures = admin_client.create_topics(new_topics=[new_topic])
                futures[topic].result()
            except TopicAlreadyExistsError:
                existing.append(topic)
            else:
                created.append(topic)
    finally:
        if owns_client:
            admin_client.close()

    return {"existing": existing, "created": created}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    settings = load_settings(args.config)
    result = ensure_topics(settings)
    print(f"Existing topics: {result['existing']}")
    print(f"Created topics: {result['created']}")


if __name__ == "__main__":
    main()
