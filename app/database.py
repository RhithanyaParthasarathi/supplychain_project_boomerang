# app/database.py
import motor.motor_asyncio
from app.config import MONGODB_URI, DATABASE_NAME

# Create a client to connect to MongoDB.
# This client object is created once and reused for all operations.
client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)

# Get a reference to the database.
# The database and its collections are created lazily on their first use.
database = client[DATABASE_NAME]

# This is a dependency that our API endpoints will use
# to get a reference to the 'returns' collection.
def get_returns_collection():
    return database.get_collection("returns")

# Function to get the orders collection for validation
def get_orders_collection():
    return database.get_collection("orders")
