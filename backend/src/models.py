from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

class User(BaseModel):
    id: Optional[str] = Field(None, alias="_id") 
    email: EmailStr
    hashed_password: str
    full_name: str
    role: str
    verification_status: str = "unverified"
    avatar_url: Optional[str] = None
    created_at: datetime = datetime.now()

class Campaign(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    volunteer_id: str
    title: str
    description: str
    goal_amount: float
    current_amount: float = 0.0
    currency: str = "UAH"
    status: str = "active"
    image_url: Optional[str] = None
    created_at: datetime = datetime.now()
    author_name: str = "Анонімний волонтер"
    is_author_verified: bool = False

class Transaction(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    campaign_id: str
    donor_email: Optional[EmailStr] = None
    amount: float
    currency: str = "UAH"
    payment_method: str = "Monobank API"
    status: str = "pending"
    created_at: datetime = datetime.now()
