import os
from fastapi import FastAPI, HTTPException, status, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from bson import ObjectId
from database import users_collection, campaigns_collection, transactions_collection
from models import User, Campaign, Transaction, LoginRequest
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

os.makedirs("static/avatars", exist_ok=True)
os.makedirs("static/verification", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

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

# Аватар користувача
@app.post("/users/{user_id}/avatar")
async def upload_avatar(user_id: str, file: UploadFile = File(...)):
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")

    file_extension = file.filename.split(".")[-1]
    filename = f"{user_id}_avatar.{file_extension}"
    file_path = f"static/avatars/{filename}"

    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    avatar_url = f"http://127.0.0.1:8000/static/avatars/{filename}"

    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"avatar_url": avatar_url}}
    )

    return {
        "message": "Аватар успішно завантажено!", 
        "avatar_url": avatar_url
    }

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
    campaign = await campaigns_collection.find_one({"_id": ObjectId(transaction.campaign_id)})
    if not campaign:
        raise HTTPException(status_code=404, detail="Збір не знайдено")

    transaction_dict = transaction.model_dump(by_alias=True, exclude={"id"})
    new_transaction = await transactions_collection.insert_one(transaction_dict)
    
    return {
        "message": "Транзакцію ініційовано. Перейдіть за посиланням для оплати.",
        "transaction_id": str(new_transaction.inserted_id),
        "payment_url": campaign.get("payment_url"),
        "status": "pending"
    }

#ВЕРИФІКАЦІЯ ТА УПРАВЛІННЯ

# Логін користувача
@app.post("/login/")
async def login(credentials: LoginRequest):
    user = await users_collection.find_one({"email": credentials.email})
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Невірна пошта або пароль"
        )

    is_password_correct = pwd_context.verify(credentials.password, user["hashed_password"])
    
    if not is_password_correct:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Невірна пошта або пароль"
        )

    return {
        "message": "Вхід успішний!",
        "user_id": str(user["_id"]),
        "full_name": user["full_name"],
        "role": user["role"],
        "avatar_url": user.get("avatar_url")
    }

# Верифікація волонтера
@app.post("/users/{user_id}/verify-documents")
async def verify_documents(
    user_id: str, 
    front_side: UploadFile = File(...), 
    back_side: UploadFile = File(...), 
    selfie: UploadFile = File(...)
):
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")

    user_docs_path = f"static/verification/{user_id}"
    os.makedirs(user_docs_path, exist_ok=True)

    docs = {
        "front": front_side,
        "back": back_side,
        "selfie": selfie
    }
    
    saved_paths = {}

    for key, file in docs.items():
        file_extension = file.filename.split(".")[-1]
        filename = f"{key}.{file_extension}"
        full_path = f"{user_docs_path}/{filename}"
        
        with open(full_path, "wb") as buffer:
            buffer.write(await file.read())
        
        saved_paths[f"{key}_url"] = f"http://127.0.0.1:8000/{full_path}"

    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "verification_status": "pending",
                "document_urls": saved_paths
            }
        }
    )

    return {
        "message": "Документи надіслано на перевірку. Статус оновлено на 'pending'.",
        "files": saved_paths
    }

# Верифікація волонтера(2)
@app.put("/users/{user_id}/verify")
async def verify_user(user_id: str):
    result = await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"verification_status": "verified"}}
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
