import motor.motor_asyncio

MONGO_URL = "mongodb://localhost:27017"

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)

database = client.volunteer_platform

users_collection = database.get_collection("users")
campaigns_collection = database.get_collection("campaigns")
transactions_collection = database.get_collection("transactions")
