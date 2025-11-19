# backend/main.py
import asyncio
import random
import time
from typing import Dict, Optional

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    Header,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base, sessionmaker, Session

import secrets

# 🚨 BOT MANAGER — bắt buộc có file trading_bot_lib.py
try:
    from trading_bot_lib import BotManager, get_balance
except ImportError:
    # Nếu chưa có file thật — dùng fake để chạy UI / test hệ thống
    class BotManager:
        def __init__(self, *args, **kwargs):
            print("⚠ BOT MANAGER FAKE — UI vẫn chạy OK")

        def add_bot(self, **kwargs):
            print("📌 add_bot FAKE:", kwargs)

        def stop_all_bots(self):
            print("⛔ stop_all_bots FAKE")

        def stop_all_coins(self):
            print("🛑 stop_all_coins FAKE")

        def stop_bot(self, bot_id):
            print(f"🔇 stop_bot {bot_id} FAKE")

    def get_balance(api_key, api_secret):
        """Dummy get_balance nếu thiếu trading_bot_lib thật"""
        try:
            return 1000.0
        except Exception:
            return None


# ==================== DATABASE ====================
DATABASE_URL = "sqlite:///./app.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, nullable=False)
    password = Column(String(255), nullable=False)

    api_key = Column(String(255), nullable=True)
    api_secret = Column(String(255), nullable=True)


class BotConfig(Base):
    __tablename__ = "bot_configs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)

    bot_mode = Column(
        String(50), nullable=False
    )  # "reversal" / "continuation" / future modes
    symbol = Column(String(50), nullable=False)
    lev = Column(Integer, nullable=False, default=20)
    percent = Column(Float, nullable=False, default=50.0)

    tp = Column(Float, nullable=False)
    sl = Column(Float, nullable=False)
    roi_trigger = Column(Float, nullable=True)
    bot_count = Column(Integer, nullable=False, default=1)


Base.metadata.create_all(bind=engine)


# ==================== FASTAPI APP ====================
app = FastAPI(title="Quan Trading Backend", version="2.0")

# Cho phép frontend kết nối mọi nơi
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static frontend (nếu cần)
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")


# ==================== TOKEN / AUTH ====================
TOKEN_STORE: Dict[str, int] = {}  # token -> user_id mapping


def create_token(user_id: int) -> str:
    token = secrets.token_hex(32)
    TOKEN_STORE[token] = user_id
    return token


# Dependency: DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_current_user(
    x_auth_token: str = Header(..., alias="X-Auth-Token"),
    db: Session = Depends(get_db),
):
    uid = TOKEN_STORE.get(x_auth_token)
    if not uid:
        raise HTTPException(401, detail="Token hết hạn hoặc không hợp lệ")

    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(401, detail="User không tồn tại")
    return user


# ==================== Pydantic MODELS ====================
class RegisterReq(BaseModel):
    username: str
    password: str


class LoginReq(BaseModel):
    username: str
    password: str


class SetupReq(BaseModel):
    api_key: str
    api_secret: str


class AddBotReq(BaseModel):
    bot_mode: str
    symbol: str
    lev: int
    percent: float
    tp: float
    sl: float
    roi_trigger: Optional[float] = None
    bot_count: int = 1


# ==================== BOT MANAGER STORE ====================
BOT_MANAGERS: Dict[int, BotManager] = {}  # user_id -> BotManager instance


def get_bm(user: User, db: Session) -> BotManager:
    """
    Lấy BotManager cho user; nếu chưa có thì khởi tạo và restore bots từ DB.
    """
    bm
