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

import secrets

# 🚨 BOT MANAGER — bắt buộc có file trading_bot_lib.py
try:
    from trading_bot_lib import BotManager
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

# Serve giao diện frontend
@app.get("/")
def read_index():
    return FileResponse("frontend/index.html")

app.mount("/frontend", StaticFiles(directory="frontend", html=True), name="frontend")


# ==================== DB DEPENDENCY ====================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== TOKEN STORE ====================
TOKEN_STORE: Dict[str, int] = {}  # token → user_id mapping

def create_token(user_id: int) -> str:
    token = secrets.token_hex(32)
    TOKEN_STORE[token] = user_id
    return token


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


# ==================== PYDANTIC MODELS ==============
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
    bot_mode: str = Field(default="static")  # static / dynamic
    symbol: Optional[str] = None
    lev: int = 10
    percent: float = 5
    tp: float = 50
    sl: float = 0
    roi_trigger: float = 0
    bot_count: int = 1

class StopBotReq(BaseModel):
    bot_id: int


# ==================== BOT MANAGER STORAGE ====================
BOT_MANAGERS: Dict[int, BotManager] = {}


def restore_bots(user: User, bm: BotManager, db: Session):
    """ Khôi phục các bot từ DB vào RAM """
    configs = db.query(BotConfig).filter(BotConfig.user_id == user.id).all()
    for cfg in configs:
        try:
            bm.add_bot(
                symbol=cfg.symbol,
                lev=cfg.lev,
                percent=cfg.percent,
                tp=cfg.tp,
                sl=cfg.sl,
                roi_trigger=cfg.roi_trigger,
                bot_mode=cfg.bot_mode,
                bot_count=cfg.bot_count,
                strategy_type="RSI-volume-auto",
            )
        except Exception as e:
            print("⚠ restore_bots lỗi:", e)


def get_bm(user: User, db: Session) -> BotManager:
    """ Lấy BotManager đã tồn tại, hoặc khởi tạo mới """
    bm = BOT_MANAGERS.get(user.id)
    if bm is None:
        if not (user.api_key and user.api_secret):
            raise HTTPException(400, "User chưa cấu hình API Binance")
        bm = BotManager(api_key=user.api_key, api_secret=user.api_secret)
        BOT_MANAGERS[user.id] = bm
        restore_bots(user, bm, db)
    return bm


# ==================== AUTH API ====================
@app.post("/api/register")
def register(payload: RegisterReq, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(400, "Username đã tồn tại")
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

@app.post("/api/setup-account")
def setup(payload: SetupReq, current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current.api_key = payload.api_key
    current.api_secret = payload.api_secret
    db.add(current)
    db.commit()
    return {"ok": True}


# ==================== SUMMARY / BOTS ====================
@app.get("/api/summary")
def summary(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    configs = db.query(BotConfig).filter(BotConfig.user_id == current.id).all()
    total_bots = len(configs)
    return {
        "total_bots": total_bots,
        "username": current.username,
    }


@app.get("/api/bots")
def get_bots(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    configs = db.query(BotConfig).filter(BotConfig.user_id == current.id).all()
    bots = []
    for cfg in configs:
        bots.append({
            "bot_id": cfg.id,
            "mode": cfg.bot_mode,
            "symbol": cfg.symbol,
            "lev": cfg.lev,
            "percent": cfg.percent,
            "tp": cfg.tp,
            "sl": cfg.sl,
            "roi_trigger": cfg.roi_trigger,
            "bot_count": cfg.bot_count,
        })
    return {"bots": bots}


@app.post("/api/add-bot")
def add_bot(
    payload: AddBotReq,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bm = get_bm(current, db)
    bm.add_bot(
        symbol=payload.symbol,
        lev=payload.lev,
        percent=payload.percent,
        tp=payload.tp,
        sl=payload.sl,
        roi_trigger=payload.roi_trigger,
        bot_mode=payload.bot_mode,
        bot_count=payload.bot_count,
        strategy_type="RSI-volume-auto",
    )

    cfg = BotConfig(
        user_id=current.id,
        bot_mode=payload.bot_mode,
        symbol=payload.symbol,
        lev=payload.lev,
        percent=payload.percent,
        tp=payload.tp,
        sl=payload.sl,
        roi_trigger=payload.roi_trigger,
        bot_count=payload.bot_count,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)

    return {"ok": True, "bot_id": cfg.id}


@app.post("/api/stop-all-bots")
def stop_all_bots(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bm = get_bm(current, db)
    bm.stop_all_bots()
    return {"ok": True}


# ==================== WS DEMO (giá & PNL ảo) ====================
@app.websocket("/ws/price")
async def ws_price(ws: WebSocket, token: str):
    await ws.accept()
    # Không check token sâu, demo thôi
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


@app.websocket("/ws/pnl")
async def ws_pnl(ws: WebSocket, token: str):
    await ws.accept()
    balance = 1000.0
    try:
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


# ==================== CHẠY LOCAL ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
