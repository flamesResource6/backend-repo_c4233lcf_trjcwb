"""
Database Schemas for Game Store

Each Pydantic model represents a collection in your MongoDB database.
Collection name is the lowercase of the class name.

- User -> "user"
- Game -> "game"
- Order -> "order"
- Session -> "session"
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List

class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    password_hash: str = Field(..., description="Hashed password")
    role: str = Field("user", description="Role: user or admin")
    is_active: bool = Field(True, description="Whether user is active")

class Game(BaseModel):
    title: str = Field(..., description="Game title")
    platform: str = Field(..., description="Platform: PC or Mobile")
    description: Optional[str] = Field(None, description="Game description")
    price: float = Field(..., ge=0, description="Price")
    images: List[str] = Field(default_factory=list, description="Image URLs")
    category: Optional[str] = Field(None, description="Category/Genre")
    in_stock: bool = Field(True, description="In stock")

class Order(BaseModel):
    user_id: Optional[str] = Field(None, description="User ID")
    game_id: str = Field(..., description="Purchased game ID")
    transaction_id: str = Field(..., description="Nagad transaction ID")
    payment_method: str = Field("NAGAD", description="Payment method")
    delivery_email: EmailStr = Field(..., description="Email to receive game/key")
    status: str = Field("pending", description="pending, verified, delivered, cancelled")

class Session(BaseModel):
    user_id: str = Field(..., description="User ID")
    token: str = Field(..., description="Session token")
    expires_at: int = Field(..., description="Unix timestamp when token expires")
