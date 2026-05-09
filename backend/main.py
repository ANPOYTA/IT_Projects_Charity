from datetime import datetime
import os
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, HTTPException, status, Header, Form, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from bson import ObjectId
from database import users_collection, campaigns_collection, transactions_collection
from models import User, Campaign, Transaction, LoginRequest, UserRegisterRequest
from typing import List
from passlib.context import CryptContext

app = FastAPI(title="Вебплатформа для зборів API")

# Налаштування CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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

# Отримати дані поточного користувача для профілю
@app.get("/users/me")
async def get_current_user(authorization: str = Header(None)):
    user_id = authorization.replace("Bearer ", "")
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    user["_id"] = str(user["_id"])
    return user

# Створити користувача
@app.post("/users/")
async def create_user(request: UserRegisterRequest):
    # Додатковий бонус: перевіряємо, чи немає вже такого email в базі
    existing_user = await users_collection.find_one({"email": request.email})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Користувач з таким email вже існує"
        )

    # 1. Бекенд сам склеює ім'я
    full_name = f"{request.name} {request.surname}"
    
    # 2. Бекенд сам хешує пароль
    hashed_pw = pwd_context.hash(request.password)
    
    # 3. Формуємо правильний словник для бази даних
    user_dict = {
        "email": request.email,
        "hashed_password": hashed_pw,
        "full_name": full_name,
        "phone": request.phone,
        "role": "volunteer",
        "verification_status": "unverified"
    }
    
    # 4. Зберігаємо в MongoDB Atlas
    new_user = await users_collection.insert_one(user_dict)
    
    return {
        "message": "Користувача успішно створено!",
        "user_id": str(new_user.inserted_id)
    }

# 2. Мої збори (щоб зник напис про верифікацію або з'явилися картки)
@app.get("/users/me/campaigns")
async def get_my_campaigns(authorization: str = Header(None)):
    user_id = authorization.replace("Bearer ", "")
    campaigns = []
    cursor = campaigns_collection.find({"volunteer_id": user_id})
    async for document in cursor:
        document["_id"] = str(document["_id"])
        campaigns.append(document)
    return campaigns

@app.get("/users/me/donations")
async def get_my_donations(authorization: str = Header(None)):
    return []

# Отримати всі збори конкретного волонтера
@app.get("/users/{user_id}/campaigns", response_model=List[Campaign])
async def get_user_campaigns(user_id: str):
    campaigns = []
    cursor = campaigns_collection.find({"volunteer_id": user_id})
    async for document in cursor:
        document["_id"] = str(document["_id"])
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
        document["_id"] = str(document["_id"])
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

    avatar_url = f"/static/avatars/{filename}"

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
async def create_campaign(
    title: str = Form(...),
    description: str = Form(...),
    goal_amount: float = Form(...),
    payment_url: str = Form(...),
    image: UploadFile = File(None),
    authorization: str = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail="Токен відсутній")
    
    # Витягуємо ID волонтера
    volunteer_id = authorization.replace("Bearer ", "")
    
    # Перевіряємо користувача в базі
    user = await users_collection.find_one({"_id": ObjectId(volunteer_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")
        
    # ВАЖЛИВО: Тільки верифіковані волонтери можуть створювати збори
    if user.get("verification_status") != "verified":
        raise HTTPException(
            status_code=403, 
            detail="Щоб розмістити збір, пройдіть верифікацію у профілі"
        )

    # Логіка збереження картинки
    image_url = "http://127.0.0.1:8000/static/default-campaign.jpg" # Заглушка
    if image:
        # Створюємо папку, якщо її немає
        os.makedirs("static/campaigns", exist_ok=True)
        
        file_extension = image.filename.split(".")[-1]
        filename = f"{ObjectId()}_{image.filename}" # Унікальне ім'я файлу
        file_path = f"static/campaigns/{filename}"

        with open(file_path, "wb") as buffer:
            buffer.write(await image.read())
        
        image_url = f"/{file_path}"

    # Створюємо документ для MongoDB
    new_campaign = {
        "volunteer_id": volunteer_id,
        "title": title,
        "description": description,
        "goal_amount": goal_amount,
        "current_amount": 0.0,
        "payment_url": payment_url,
        "image_url": image_url,
        "status": "active",
        "author_name": user.get("full_name"),
        "is_author_verified": True,
        "created_at": datetime.now() # Не забудь імпортувати datetime
    }

    result = await campaigns_collection.insert_one(new_campaign)
    return {"message": "Збір створено!", "id": str(result.inserted_id)}

# Отримання списку всіх зборів на головному екрані
@app.get("/campaigns/", response_model=List[Campaign])
async def get_all_campaigns(limit: int = 6):
    campaigns = []
    cursor = campaigns_collection.find({"status": "active"}).limit(limit)
    
    async for document in cursor:
        document["_id"] = str(document["_id"])
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

# Новий ендпоінт для верифікації
@app.post("/users/verify")
async def process_verification(
    passport_id: str = Form(...),
    photo_front: UploadFile = File(...),
    photo_back: UploadFile = File(...),
    photo_selfie: UploadFile = File(...),
    authorization: str = Header(None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail="Токен відсутній")
    
    user_id = authorization.replace("Bearer ", "")
    
    # Створюємо папку для документів користувача
    user_docs_path = f"static/verification/{user_id}"
    os.makedirs(user_docs_path, exist_ok=True)

    # Зберігаємо файли
    file_map = {
        "front": photo_front,
        "back": photo_back,
        "selfie": photo_selfie
    }
    
    saved_urls = {}
    for key, file in file_map.items():
        ext = file.filename.split(".")[-1]
        path = f"{user_docs_path}/{key}.{ext}"
        with open(path, "wb") as buffer:
            buffer.write(await file.read())
        saved_urls[f"{key}_url"] = f"/{path}"

    # Оновлюємо статус в базі Atlas
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "verification_status": "pending",
                "passport_id": passport_id,
                "document_urls": saved_urls
            }
        }
    )

    return {"message": "Документи отримано"}
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
