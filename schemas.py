"""
Database Schemas for Premium Kids Fashion E‑commerce

Each Pydantic model represents a collection in MongoDB. The collection name is the lowercase of the class name.
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, EmailStr


class Users(BaseModel):
    name: str = Field(..., min_length=2)
    email: EmailStr
    role: Literal["user", "admin"] = "user"
    # Optional fields for profile
    avatar_url: Optional[str] = None


class Products(BaseModel):
    title: str
    description: str
    price: float = Field(..., ge=0)
    mrp: float = Field(..., ge=0)
    gender: Literal["girls", "boys", "unisex"]
    category: str
    stock: int = Field(..., ge=0)
    tags: List[str] = []
    image_urls: List[str] = []


class Wishlist(BaseModel):
    user_id: str
    product_id: str


class Cart(BaseModel):
    user_id: str
    product_id: str
    quantity: int = Field(..., ge=1)


class Orders(BaseModel):
    user_id: str
    items: List[dict]
    total_price: float = Field(..., ge=0)
    payment_status: Literal["pending", "paid", "failed", "refunded"] = "pending"
    shipping_status: Literal["pending", "processing", "shipped", "delivered", "cancelled"] = "pending"
    razorpay_payment_id: Optional[str] = None
