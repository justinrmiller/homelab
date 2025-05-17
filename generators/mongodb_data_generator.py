from pymongo import MongoClient
from faker import Faker
import random

# Configuration
MONGO_HOST = 'localhost'
MONGO_PORT = 27017
DB_NAME = 'appdb'
COLLECTION_NAME = 'users'
USERNAME = 'mongo'
PASSWORD = 'mongo'

# Connect to MongoDB with authentication
uri = f"mongodb://{USERNAME}:{PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/{DB_NAME}"
print(uri)
client = MongoClient(uri)

db = client[DB_NAME]
collection = db[COLLECTION_NAME]

# Use Faker to generate sample user data
fake = Faker()

def generate_user():
    return {
        "name": fake.name(),
        "email": fake.email(),
        "address": fake.address(),
        "created_at": fake.date_time_this_decade(),
        "is_active": random.choice([True, False]),
        "age": random.randint(18, 80)
    }

# Generate and insert 10,000 users
batch_size = 1000
for i in range(0, 10000, batch_size):
    batch = [generate_user() for _ in range(batch_size)]
    result = collection.insert_many(batch)
    print(f"Inserted batch {i + 1}–{i + batch_size}, inserted IDs count: {len(result.inserted_ids)}")

print("✅ Done inserting 10,000 users.")
