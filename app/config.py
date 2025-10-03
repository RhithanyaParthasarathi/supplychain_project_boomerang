# app/config.py

# --- MongoDB Config ---
MONGODB_URI = "mongodb://localhost:27017"
DATABASE_NAME = "gadgetgrove"

# --- Kafka Config ---
KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
KAFKA_TOPIC_RETURN_REQUESTS = "gadgetgrove.returns.requests"
KAFKA_TOPIC_ITEMS_RECEIVED = "gadgetgrove.returns.received"
KAFKA_TOPIC_ITEMS_INSPECTED = "gadgetgrove.returns.inspected"
KAFKA_TOPIC_CASES_CLOSED = "gadgetgrove.returns.closed"