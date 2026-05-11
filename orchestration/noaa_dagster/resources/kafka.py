"""Kafka admin resource for Dagster."""

import os

from confluent_kafka.admin import AdminClient, NewTopic
from dagster import ConfigurableResource


class KafkaResource(ConfigurableResource):
    bootstrap_servers: str = "localhost:9092"

    def get_admin(self) -> AdminClient:
        return AdminClient({"bootstrap.servers": self.bootstrap_servers})

    def ensure_topic(self, topic: str, num_partitions: int = 12, replication_factor: int = 1) -> bool:
        """Create topic if not exists. Returns True if created, False if already existed."""
        admin = self.get_admin()
        existing = admin.list_topics(timeout=5).topics
        if topic in existing:
            return False
        new_topic = NewTopic(topic, num_partitions=num_partitions, replication_factor=replication_factor)
        fs = admin.create_topics([new_topic])
        for t, f in fs.items():
            f.result()
        return True

    def get_consumer_lag(self, group_id: str, topic: str) -> int:
        """Return total consumer lag for a group+topic."""
        from confluent_kafka import Consumer, TopicPartition

        consumer = Consumer({
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": group_id,
        })
        metadata = consumer.list_topics(topic, timeout=5)
        partitions = [
            TopicPartition(topic, p) for p in metadata.topics[topic].partitions
        ]
        committed = consumer.committed(partitions, timeout=5)
        total_lag = 0
        for tp in committed:
            lo, hi = consumer.get_watermark_offsets(tp, timeout=5)
            if tp.offset >= 0:
                total_lag += max(0, hi - tp.offset)
        consumer.close()
        return total_lag


def kafka_resource_from_env() -> KafkaResource:
    return KafkaResource(
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
    )
