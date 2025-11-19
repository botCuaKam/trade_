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
    bm = BOT_MANAGERS.get(user.id)
    if bm is None:
        if not (user.api_key and user.api_secret):
            raise HTTPException(400, "User chưa cấu hình API Binance")

        bm = BotManager(api_key=user.api_key, api_secret=user.api_secret)
        BOT_MANAGERS[user.id] = bm
        restore_bots(user, bm, db)
    return bm


def restore_bots(user: User, bm: BotManager, db: Session):
    """
    Đọc bot_configs trong DB và add lại vào BotManager khi app khởi động / user login.
    """
    configs = db.query(BotConfig).filter(BotConfig.user_id == user.id).all()
    for cfg in configs:
        bm.add_bot(
            symbol=cfg.symbol,
            lev=cfg.lev,
            percent=cfg.percent,
            tp=cfg.tp,
            sl=cfg.sl,
            roi_trigger=cfg.roi_trigger,
            bot_id=cfg.id,
            bot_mode=cfg.bot_mode,
            bot_count=cfg.bot_count,
        )


# ==================== AUTH ENDPOINTS ====================
@app.post("/api/register")
def register(payload: RegisterReq, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(400, detail="Tên đăng nhập đã tồn tại")

    user = User(username=payload.username, password=payload.password)
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(user.id)
    return {"token": token, "username": user.username}


@app.post("/api/login")
def login(payload: LoginReq, db: Session = Depends(get_db)):
    user = (
        db.query(User)
        .filter(
            User.username == payload.username,
            User.password == payload.password,
        )
        .first()
    )
    if not user:
        raise HTTPException(401, detail="Sai username hoặc password")
    token = create_token(user.id)
    return {"token": token, "username": user.username}


@app.get("/api/me")
def me(current: User = Depends(get_current_user)):
    return {
        "id": current.id,
        "username": current.username,
        "has_api": bool(current.api_key and current.api_secret),
    }


# ==================== SETUP BINANCE API ====================
@app.get("/api/setup-account")
def get_setup(current: User = Depends(get_current_user)):
    return {"configured": bool(current.api_key and current.api_secret)}


@app.post("/api/setup-account")
def setup(
    payload: SetupReq,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current.api_key = payload.api_key
    current.api_secret = payload.api_secret
    db.add(current)
    db.commit()
    return {"ok": True}


# ==================== SUMMARY / BOTS ====================
@app.get("/api/account/balance")
def api_account_balance(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Trả về số dư khả dụng thực tế trên Binance Futures cho user hiện tại.
    UI có thể gọi endpoint này để hiển thị balance ngoài WebSocket.
    """
    if not current.api_key or not current.api_secret:
        raise HTTPException(status_code=400, detail="User chưa cấu hình API Binance")

    balance = get_balance(current.api_key, current.api_secret)
    if balance is None:
        raise HTTPException(status_code=500, detail="Không lấy được số dư từ Binance")

    return {
        "asset": "USDC",
        "available_balance": round(float(balance), 2),
    }


@app.get("/api/summary")
def summary(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    configs = db.query(BotConfig).filter(BotConfig.user_id == current.id).all()
    total_bots = len(configs)
    return {
        "total_bots": total_bots,
        "username": current.username,
    }


@app.get("/api/bots")
def get_bots(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    configs = db.query(BotConfig).filter(BotConfig.user_id == current.id).all()
    bots = []
    for cfg in configs:
        bots.append(
            {
                "id": cfg.id,
                "symbol": cfg.symbol,
                "lev": cfg.lev,
                "percent": cfg.percent,
                "tp": cfg.tp,
                "sl": cfg.sl,
                "roi_trigger": cfg.roi_trigger,
                "bot_mode": cfg.bot_mode,
                "bot_count": cfg.bot_count,
            }
        )
    return {"bots": bots}


@app.post("/api/add-bot")
def add_bot(
    payload: AddBotReq,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bm = get_bm(current, db)

    # Lưu config vào DB
    cfg = BotConfig(
        user_id=current.id,
        bot_mode=payload.bot_mode,
        symbol=payload.symbol.upper(),
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

    # Thêm bot vào BotManager thật
    bm.add_bot(
        symbol=cfg.symbol,
        lev=cfg.lev,
        percent=cfg.percent,
        tp=cfg.tp,
        sl=cfg.sl,
        roi_trigger=cfg.roi_trigger,
        bot_id=cfg.id,
        bot_mode=cfg.bot_mode,
        bot_count=cfg.bot_count,
    )

    return {"ok": True, "id": cfg.id}


@app.post("/api/stop-bot/{bot_id}")
def stop_bot(
    bot_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bm = get_bm(current, db)

    cfg = (
        db.query(BotConfig)
        .filter(BotConfig.id == bot_id, BotConfig.user_id == current.id)
        .first()
    )
    if not cfg:
        raise HTTPException(404, "Bot không tồn tại")

    bm.stop_bot(bot_id)
    db.delete(cfg)
    db.commit()
    return {"ok": True}


@app.post("/api/stop-all-bots")
def stop_all_bots(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bm = get_bm(current, db)
    bm.stop_all_bots()

    db.query(BotConfig).filter(BotConfig.user_id == current.id).delete()
    db.commit()
    return {"ok": True}


# ==================== WEBSOCKET: GIÁ / PnL ====================
@app.websocket("/ws/price")
async def ws_price(ws: WebSocket, symbol: str = "BTCUSDT"):
    await ws.accept()
    try:
        while True:
            # TODO: ở đây có thể gắn WebSocket Binance thật để stream giá
            price = 60000 + random.uniform(-1000, 1000)
            data = {
                "symbol": symbol,
                "price": price,
                "timestamp": int(time.time()),
            }
            await ws.send_json(data)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        print("🔌 Client đóng WebSocket /ws/price")
    except Exception as e:
        print("❌ WS error /ws/price:", e)


@app.websocket("/ws/pnl")
async def ws_pnl(ws: WebSocket, token: str):
    """WebSocket gửi số dư thật từ Binance cho frontend theo thời gian thực"""
    await ws.accept()
    db: Session = SessionLocal()
    try:
        uid = TOKEN_STORE.get(token)
        if not uid:
            await ws.send_json({"error": "Token không hợp lệ hoặc hết hạn"})
            await ws.close(code=4001)
            return

        user = db.query(User).filter(User.id == uid).first()
        if not user or not user.api_key or not user.api_secret:
            await ws.send_json({"error": "User chưa cấu hình API Binance"})
            await ws.close(code=4002)
            return

        while True:
            balance = get_balance(user.api_key, user.api_secret)
            if balance is None:
                await ws.send_json(
                    {
                        "error": "Không lấy được số dư từ Binance",
                        "timestamp": int(time.time()),
                    }
                )
            else:
                await ws.send_json(
                    {
                        "balance": round(float(balance), 2),
                        "timestamp": int(time.time()),
                    }
                )

            # Đợi 5 giây rồi cập nhật lại để tránh spam API Binance
            await asyncio.sleep(5)

    except WebSocketDisconnect:
        print("🔌 Client đóng WebSocket /ws/pnl")
    except Exception as e:
        print("❌ WS error /ws/pnl:", e)
    finally:
        db.close()


# ==================== CHẠY LOCAL ====================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
