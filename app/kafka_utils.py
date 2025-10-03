# app/kafka_utils.py
import json
from kafka import KafkaProducer, KafkaConsumer
from app.config import KAFKA_BOOTSTRAP_SERVERS

def create_kafka_producer():
    """
    Creates and returns a Kafka Producer instance.
    This producer serializes message values as JSON strings.
    """
    return KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )

def create_kafka_consumer(topic_id, group_id="gadgetgrove-workers"):
    """
    Creates and returns a Kafka Consumer for a given topic.
    This consumer deserializes JSON string message values.
    """
    return KafkaConsumer(
        topic_id,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset='earliest',  # Start reading from the beginning of the topic
        group_id=group_id,
        value_deserializer=lambda v: json.loads(v.decode('utf-8'))
    )