import motor.motor_asyncio

MONGO_URL = "mongodb+srv://admin:P%40ssword123@cluster0.vtalxu0.mongodb.net/?appName=Cluster0"

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)

database = client.volunteer_platform

users_collection = database.get_collection("users")
campaigns_collection = database.get_collection("campaigns")
transactions_collection = database.get_collection("transactions")
loginrequests_collection = database.get_collection("loginrequests")
