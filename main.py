import os
import time
import secrets
import hashlib
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User as UserSchema, Game as GameSchema, Order as OrderSchema, Session as SessionSchema

app = FastAPI(title="Game Store API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Utilities ----------
COL_USER = "user"
COL_GAME = "game"
COL_ORDER = "order"
COL_SESSION = "session"

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")


def hash_password(password: str) -> str:
    salted = (SECRET_KEY + password).encode()
    return hashlib.sha256(salted).hexdigest()


def create_session(user_id: str) -> str:
    token = secrets.token_hex(32)
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    doc = SessionSchema(user_id=user_id, token=token, expires_at=expires_at)
    create_document(COL_SESSION, doc)
    return token


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    token: str
    role: str
    name: str
    email: EmailStr


async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1]
    sess = db[COL_SESSION].find_one({"token": token})
    if not sess:
        return None
    if int(time.time()) > int(sess.get("expires_at", 0)):
        return None
    user = db[COL_USER].find_one({"_id": oid(sess["user_id"])}) if ObjectId.is_valid(sess.get("user_id", "")) else None
    return user


# ---------- Public Endpoints ----------
@app.get("/")
def root():
    return {"message": "Game Store Backend Running"}


@app.get("/test")
def test_database():
    status = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "collections": [],
    }
    try:
        if db is not None:
            status["database"] = "✅ Connected"
            status["collections"] = db.list_collection_names()
    except Exception as e:
        status["database"] = f"⚠️ {str(e)[:60]}"
    return status


# ---------- Auth ----------
@app.post("/auth/register", response_model=TokenResponse)
def register(payload: RegisterRequest):
    existing = db[COL_USER].find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_doc = UserSchema(
        name=payload.name,
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role="user",
        is_active=True,
    )
    user_id = create_document(COL_USER, user_doc)
    token = create_session(user_id)
    return TokenResponse(token=token, role="user", name=payload.name, email=payload.email.lower())


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest):
    user = db[COL_USER].find_one({"email": payload.email.lower()})
    if not user or user.get("password_hash") != hash_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_session(str(user["_id"]))
    return TokenResponse(token=token, role=user.get("role", "user"), name=user.get("name", ""), email=user.get("email", ""))


@app.get("/me")
async def me(user=Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user["_id"] = str(user["_id"])
    user.pop("password_hash", None)
    return user


# ---------- Games (Public) ----------
@app.get("/games")
def list_games(
    search: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    q = {}
    if platform:
        q["platform"] = {"$regex": f"^{platform}$", "$options": "i"}
    if category:
        q["category"] = {"$regex": category, "$options": "i"}
    if search:
        q["$or"] = [
            {"title": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}},
        ]
    docs = db[COL_GAME].find(q).limit(50)
    games = []
    for d in docs:
        d["_id"] = str(d["_id"]) 
        games.append(d)
    return games


@app.get("/games/{game_id}")
def get_game(game_id: str):
    doc = db[COL_GAME].find_one({"_id": oid(game_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Game not found")
    doc["_id"] = str(doc["_id"]) 
    return doc


# ---------- Admin middleware ----------
async def require_admin(user=Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ---------- Admin: Games CRUD ----------
class GameCreateRequest(BaseModel):
    title: str
    platform: str
    price: float
    description: Optional[str] = None
    images: List[str] = []
    category: Optional[str] = None
    in_stock: bool = True


@app.post("/admin/games")
def create_game(payload: GameCreateRequest, user=Depends(require_admin)):
    game = GameSchema(
        title=payload.title,
        platform=payload.platform,
        description=payload.description,
        price=payload.price,
        images=payload.images or [],
        category=payload.category,
        in_stock=payload.in_stock,
    )
    game_id = create_document(COL_GAME, game)
    return {"_id": game_id}


class GameUpdateRequest(BaseModel):
    title: Optional[str] = None
    platform: Optional[str] = None
    price: Optional[float] = None
    description: Optional[str] = None
    images: Optional[List[str]] = None
    category: Optional[str] = None
    in_stock: Optional[bool] = None


@app.put("/admin/games/{game_id}")
def update_game(game_id: str, payload: GameUpdateRequest, user=Depends(require_admin)):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        return {"updated": False}
    updates["updated_at"] = int(time.time())
    res = db[COL_GAME].update_one({"_id": oid(game_id)}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Game not found")
    return {"updated": True}


@app.delete("/admin/games/{game_id}")
def delete_game(game_id: str, user=Depends(require_admin)):
    res = db[COL_GAME].delete_one({"_id": oid(game_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Game not found")
    return {"deleted": True}


# ---------- Orders ----------
class CreateOrderRequest(BaseModel):
    game_id: str
    transaction_id: str
    delivery_email: EmailStr


@app.post("/orders")
async def create_order(payload: CreateOrderRequest, user=Depends(get_current_user)):
    game = db[COL_GAME].find_one({"_id": oid(payload.game_id)})
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    # simple duplicate transaction check
    if db[COL_ORDER].find_one({"transaction_id": payload.transaction_id}):
        raise HTTPException(status_code=400, detail="Transaction ID already used")

    order = OrderSchema(
        user_id=str(user["_id"]) if user else None,
        game_id=payload.game_id,
        transaction_id=payload.transaction_id,
        payment_method="NAGAD",
        delivery_email=payload.delivery_email,
        status="pending",
    )
    order_id = create_document(COL_ORDER, order)
    return {"_id": order_id, "message": "Order placed. Delivery within 2 hours after verification."}


@app.get("/orders/mine")
async def my_orders(user=Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    docs = db[COL_ORDER].find({"user_id": str(user["_id"])})
    out = []
    for d in docs:
        d["_id"] = str(d["_id"]) 
        out.append(d)
    return out


# ---------- Admin: Orders ----------
@app.get("/admin/orders")
def admin_list_orders(status: Optional[str] = Query(None), user=Depends(require_admin)):
    q = {}
    if status:
        q["status"] = status
    docs = db[COL_ORDER].find(q).limit(100)
    out = []
    for d in docs:
        d["_id"] = str(d["_id"]) 
        out.append(d)
    return out


class UpdateOrderStatusRequest(BaseModel):
    status: str  # verified, delivered, cancelled


@app.post("/admin/orders/{order_id}/status")
def update_order_status(order_id: str, payload: UpdateOrderStatusRequest, user=Depends(require_admin)):
    if payload.status not in {"pending", "verified", "delivered", "cancelled"}:
        raise HTTPException(status_code=400, detail="Invalid status")
    res = db[COL_ORDER].update_one({"_id": oid(order_id)}, {"$set": {"status": payload.status, "updated_at": int(time.time())}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"updated": True}


# ---------- Schema endpoint for viewer ----------
@app.get("/schema")
def get_schema_definitions():
    return {
        "user": UserSchema.model_json_schema(),
        "game": GameSchema.model_json_schema(),
        "order": OrderSchema.model_json_schema(),
        "session": SessionSchema.model_json_schema(),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
