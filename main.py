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
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base, sessionmaker, Session

import jwt

from trading_bot_lib import (
    TradingBotConfig,
    TradingBotManager,
)

# ==================== DB CONFIG ====================
DATABASE_URL = "postgresql://postgres:postgres@db:5432/postgres"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

JWT_SECRET = "quan_super_secret"
JWT_ALG = "HS256"


# ==================== MODELS ====================
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
    bot_mode = Column(String(20), nullable=False)   # static / dynamic
    symbol = Column(String(50), nullable=True)
    lev = Column(Integer, nullable=False)
    percent = Column(Float, nullable=False)
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
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Trang chủ: trả về giao diện chính
@app.get("/")
def read_index():
    return FileResponse("frontend/index.html")

# Serve giao diện frontend
app.mount("/frontend", StaticFiles(directory="frontend", html=True), name="frontend")


# ==================== DB Dependency ====================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== JWT HELPERS ====================
def create_token(user_id: int) -> str:
    payload = {"user_id": user_id, "iat": int(time.time())}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> int:
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return data["user_id"]
    except Exception:
        raise HTTPException(401, "Token không hợp lệ hoặc đã hết hạn")


# ==================== Pydantic Schemas ====================
class RegisterReq(BaseModel):
    username: str
    password: str


class LoginReq(BaseModel):
    username: str
    password: str


class ApiKeyReq(BaseModel):
    api_key: str
    api_secret: str


class BotConfigReq(BaseModel):
    bot_mode: str = Field(..., description="static / dynamic")
    symbol: Optional[str] = None
    lev: int
    percent: float
    tp: float
    sl: float
    roi_trigger: Optional[float] = None
    bot_count: int = 1


# ==================== AUTH DEPENDENCY ====================
async def get_current_user(
    x_auth_token: str = Header(..., alias="X-Auth-Token"),
    db: Session = Depends(get_db),
):
    uid = decode_token(x_auth_token)
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(401, "User không tồn tại")
    return user


# ==================== AUTH ROUTES ====================
@app.post("/api/register-and-login")
def register_and_login(payload: RegisterReq, db: Session = Depends(get_db)):
    existed = db.query(User).filter(User.username == payload.username).first()
    if existed:
        # Nếu user đã tồn tại -> login luôn
        if existed.password != payload.password:
            raise HTTPException(400, "Sai password của user đã tồn tại")
        token = create_token(existed.id)
        return {"token": token, "username": existed.username}

    user = User(username=payload.username, password=payload.password)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(user.id)
    return {"token": token, "username": user.username}


@app.post("/api/login")
def login(payload: LoginReq, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        User.username == payload.username,
        User.password == payload.password
    ).first()
    if not user:
        raise HTTPException(401, "Sai username/password")
    token = create_token(user.id)
    return {"token": token, "username": user.username}


# ==================== ACCOUNT ====================
@app.get("/api/account-status")
def status(current: User = Depends(get_current_user)):
    return {"configured": bool(current.api_key and current.api_secret)}


@app.post("/api/save-api-key")
def save_api_key(
    payload: ApiKeyReq,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current.api_key = payload.api_key
    current.api_secret = payload.api_secret
    db.add(current)
    db.commit()
    return {"ok": True}


# ==================== BOT MANAGER ====================
BOT_MANAGER = TradingBotManager()


@app.get("/api/bot-config")
def get_config(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = db.query(BotConfig).filter(BotConfig.user_id == current.id).first()
    if not cfg:
        return None
    return {
        "bot_mode": cfg.bot_mode,
        "symbol": cfg.symbol,
        "lev": cfg.lev,
        "percent": cfg.percent,
        "tp": cfg.tp,
        "sl": cfg.sl,
        "roi_trigger": cfg.roi_trigger,
        "bot_count": cfg.bot_count,
    }


@app.post("/api/bot-config")
def save_config(
    payload: BotConfigReq,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cfg = db.query(BotConfig).filter(BotConfig.user_id == current.id).first()
    if not cfg:
        cfg = BotConfig(user_id=current.id, **payload.dict())
        db.add(cfg)
    else:
        for k, v in payload.dict().items():
            setattr(cfg, k, v)
        db.add(cfg)
    db.commit()

    # Cập nhật config cho BOT_MANAGER
    config = TradingBotConfig(
        user_id=current.id,
        mode=payload.bot_mode,
        symbol=payload.symbol,
        lev=payload.lev,
        percent=payload.percent,
        tp=payload.tp,
        sl=payload.sl,
        roi_trigger=payload.roi_trigger,
        bot_count=payload.bot_count,
    )
    BOT_MANAGER.update_config(current.id, config)
    return {"ok": True}


@app.post("/api/bot-start")
def bot_start(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = db.query(BotConfig).filter(BotConfig.user_id == current.id).first()
    if not cfg:
        raise HTTPException(400, "Chưa cấu hình bot")

    if not current.api_key or not current.api_secret:
        raise HTTPException(400, "Chưa cấu hình API key Binance")

    config = TradingBotConfig(
        user_id=current.id,
        mode=cfg.bot_mode,
        symbol=cfg.symbol,
        lev=cfg.lev,
        percent=cfg.percent,
        tp=cfg.tp,
        sl=cfg.sl,
        roi_trigger=cfg.roi_trigger,
        bot_count=cfg.bot_count,
    )
    BOT_MANAGER.start_bot(user=current, config=config)
    return {"status": "started"}


@app.post("/api/bot-stop")
def bot_stop(current: User = Depends(get_current_user)):
    BOT_MANAGER.stop_bot(current.id)
    return {"status": "stopped"}


@app.get("/api/bot-status")
def bot_status(current: User = Depends(get_current_user)):
    st = BOT_MANAGER.get_status(current.id)
    return st or {"running": False}


# ==================== WS PRICE DEMO ====================
PRICE_SOCKETS: Dict[int, WebSocket] = {}


@app.websocket("/ws/price")
async def ws_price(ws: WebSocket, token: str):
    await ws.accept()
    try:
        user_id = decode_token(token)
    except Exception:
        await ws.close()
        return

    PRICE_SOCKETS[user_id] = ws
    print(f"✅ WS price connected for user {user_id}")
    try:
        while True:
            price = round(50000 + random.uniform(-1000, 1000), 2)
            data = {
                "price": price,
                "timestamp": int(time.time())
            }
            await ws.send_json(data)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        print("🔌 Client đóng WebSocket")
    except Exception as e:
        print("❌ WS error:", e)


# ==================== WS PNL DEMO ====================
PNL_SOCKETS: Dict[int, WebSocket] = {}


@app.websocket("/ws/pnl")
async def ws_pnl(ws: WebSocket, token: str):
    await ws.accept()
    try:
        user_id = decode_token(token)
    except Exception:
        await ws.close()
        return

    PNL_SOCKETS[user_id] = ws
    print(f"✅ WS pnl connected for user {user_id}")
    try:
        balance = 1000.0
        while True:
            delta = random.uniform(-10, 10)
            balance += delta
            data = {
                "balance": round(balance, 2),
                "timestamp": int(time.time())
            }
            await ws.send_json(data)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        print("🔌 Client đóng WebSocket")
    except Exception as e:
        print("❌ WS error:", e)


# ==================== CHẠY SERVER ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
