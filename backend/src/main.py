from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from bson import ObjectId
from database import users_collection, campaigns_collection, transactions_collection
from models import User, Campaign, Transaction
from typing import List
from passlib.context import CryptContext

app = FastAPI(title="Вебплатформа для зборів API")

# Налаштування CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@app.get("/")
async def root():
    return {"message": "Сервер працює."}

#КОРИСТУВАЧІ

# Створити користувача
@app.post("/users/")
async def create_user(user: User):
    safe_password = user.hashed_password[:72]
    user.hashed_password = pwd_context.hash(safe_password)
    
    user_dict = user.model_dump(by_alias=True, exclude={"id"})
    new_user = await users_collection.insert_one(user_dict)
    
    return {
        "message": "Користувача успішно створено!",
        "user_id": str(new_user.inserted_id)
    }

# Отримати всі збори конкретного волонтера
@app.get("/users/{user_id}/campaigns", response_model=List[Campaign])
async def get_user_campaigns(user_id: str):
    campaigns = []
    cursor = campaigns_collection.find({"volunteer_id": user_id})
    async for document in cursor:
        campaigns.append(Campaign(**document))
    return campaigns

# Отримати історію донатів користувача
@app.get("/users/{user_email}/donations", response_model=List[Transaction])
async def get_user_donations(user_email: str):
    transactions = []
    cursor = transactions_collection.find({
        "donor_email": user_email,
        "status": "success"
    })
    async for document in cursor:
        transactions.append(Transaction(**document))
    return transactions

#ЗБОРИ

# Створення нового збору
@app.post("/campaigns/")
async def create_campaign(campaign: Campaign):
    user = await users_collection.find_one({"_id": ObjectId(campaign.volunteer_id)})
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Користувача не знайдено"
        )
    
    if user.get("verification_status") != "verified":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Помилка: Створювати збори можуть лише верифіковані волонтери"
        )
    campaign.author_name = user.get("full_name", "Невідомий")
    campaign.is_author_verified = True

    campaign_dict = campaign.model_dump(by_alias=True, exclude={"id"})
    new_campaign = await campaigns_collection.insert_one(campaign_dict)
    
    return {
        "message": "Збір успішно створено.",
        "campaign_id": str(new_campaign.inserted_id)
    }

# Отримання списку всіх зборів на головному екрані
@app.get("/campaigns/", response_model=List[Campaign])
async def get_all_campaigns(limit: int = 6):
    campaigns = []
    cursor = campaigns_collection.find({"status": "active"}).limit(limit)
    
    async for document in cursor:
        campaigns.append(Campaign(**document))
        
    return campaigns

# Процес донату
@app.post("/donate/")
async def create_donation(transaction: Transaction):
    transaction_dict = transaction.model_dump(by_alias=True, exclude={"id"})
    new_transaction = await transactions_collection.insert_one(transaction_dict)
    fake_payment_url = f"https://api.monobank.ua/checkout/pay/{new_transaction.inserted_id}"
    
    return {
        "message": "Транзакцію ініційовано. Перейдіть за посиланням для оплати.",
        "transaction_id": str(new_transaction.inserted_id),
        "payment_url": fake_payment_url,
        "status": "pending"
    }

#ВЕРИФІКАЦІЯ ТА УПРАВЛІННЯ

# Верифікація волонтера
@app.put("/users/{user_id}/verify")
async def verify_user(user_id: str):
    result = await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"is_verified": True}}
    )
    
    if result.modified_count == 1:
        return {"message": "Користувача успішно верифіковано."}
    return {"error": "Користувача не знайдено або він вже верифікований."}

# Закриття збору
@app.put("/campaigns/{campaign_id}/close")
async def close_campaign(campaign_id: str):
    result = await campaigns_collection.update_one(
        {"_id": ObjectId(campaign_id)},
        {"$set": {"status": "closed"}}
    )
    
    if result.modified_count == 1:
        return {"message": "Збір успішно закрито!"}
    return {"error": "Збір не знайдено."}

# Фінал донату
@app.post("/webhook/payment/{transaction_id}")
async def payment_webhook(transaction_id: str):
    transaction = await transactions_collection.find_one({"_id": ObjectId(transaction_id)})
    if not transaction:
        return {"error": "Транзакцію не знайдено"}

    if transaction.get("status") == "success":
        return {"message": "Ця транзакція вже була успішно оброблена раніше."}

    campaign = await campaigns_collection.find_one({"_id": ObjectId(transaction["campaign_id"])})
    if not campaign:
        return {"error": "Збір не знайдено"}

    await transactions_collection.update_one(
        {"_id": ObjectId(transaction_id)},
        {"$set": {"status": "success"}}
    )

    new_amount = campaign["current_amount"] + transaction["amount"]

    if new_amount >= campaign["goal_amount"]:
        await campaigns_collection.update_one(
            {"_id": ObjectId(transaction["campaign_id"])},
            {"$set": {
                "current_amount": new_amount, 
                "status": "closed"
            }}
        )
        return {
            "message": "Оплата успішна! Ціль досягнуто, збір закрито.",
            "new_amount": new_amount,
            "status": "closed"
        }
    else:
        await campaigns_collection.update_one(
            {"_id": ObjectId(transaction["campaign_id"])},
            {"$set": {"current_amount": new_amount}}
        )
        return {
            "message": "Оплата пройшла успішно! Суму збору оновлено.",
            "new_amount": new_amount,
            "status": "active"
        }
