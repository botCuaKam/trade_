# backend/main.py
import asyncio
import random
import time
import os
import secrets
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
from fastapi.responses import FileResponse, RedirectResponse

from pydantic import BaseModel, Field

from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# 🚨 BOT MANAGER — dùng trading_bot_lib thật nếu có
try:
    from trading_bot_lib import BotManager, get_balance
except ImportError:
    # Nếu chưa có file thật — dùng fake để UI vẫn chạy, KHÔNG giao dịch thật
    class BotManager:
        def __init__(self, *args, **kwargs):
            print("⚠ BOT MANAGER FAKE — UI vẫn chạy OK, KHÔNG giao dịch thật")

        def add_bot(self, **kwargs):
            print("📌 add_bot FAKE:", kwargs)
            return True

        def stop_all(self):
            print("🔴 stop_all FAKE")

        def stop_all_coins(self):
            print("🔴 stop_all_coins FAKE")

        def stop_bot(self, bot_id):
            print(f"🔇 stop_bot {bot_id} FAKE")

        def get_position_summary(self):
            return {
                "total_long_count": 0,
                "total_short_count": 0,
                "total_long_pnl": 0.0,
                "total_short_pnl": 0.0,
                "total_unrealized_pnl": 0.0,
                "binance_positions": [],
            }

    def get_balance(api_key, api_secret):
        """Dummy get_balance nếu thiếu trading_bot_lib thật"""
        return 1000.0


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

    # static / dynamic (khớp với frontend)
    bot_mode = Column(String(20), nullable=False)

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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static frontend (/frontend & /)
app.mount(
    "/frontend",
    StaticFiles(directory="frontend", html=True),  # /frontend → index.html
    name="frontend",
)


@app.get("/")
async def root():
    """Truy cập / sẽ trả về frontend/index.html nếu có, nếu không thì redirect /frontend."""
    index_path = os.path.join("frontend", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return RedirectResponse(url="/frontend")


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


class BotConfigReq(BaseModel):
    bot_mode: str = Field(default="static", description="static / dynamic")
    symbol: Optional[str] = None
    lev: int = 10
    percent: float = 5.0
    tp: float = 10.0
    sl: float = 20.0
    roi_trigger: Optional[float] = None
    bot_count: int = 1


# (giữ để tương thích nếu sau này dùng API khác)
class AddBotReq(BaseModel):
    bot_mode: str = Field(default="static")  # static / dynamic
    symbol: Optional[str] = None
    lev: int = 10
    percent: float = 5
    tp: float = 50
    sl: float = 0
    roi_trigger: float = 0
    bot_count: int = 1


# ==================== BOT MANAGER STORE ====================
BOT_MANAGERS: Dict[int, BotManager] = {}


def restore_bots(user: User, bm: BotManager, db: Session):
    """Khôi phục bot từ DB vào RAM (nếu cần). Hiện tại mình chỉ dùng cấu hình + start thủ công."""
    configs = db.query(BotConfig).filter(BotConfig.user_id == user.id).all()
    for cfg in configs:
        try:
            # Nếu muốn auto start tất cả bot theo DB khi login thì bật đoạn này:
            # bm.add_bot(
            #     symbol=cfg.symbol,
            #     lev=cfg.lev,
            #     percent=cfg.percent,
            #     tp=cfg.tp,
            #     sl=cfg.sl,
            #     roi_trigger=cfg.roi_trigger,
            #     bot_mode=cfg.bot_mode,
            #     bot_count=cfg.bot_count,
            #     strategy_type="RSI-volume-auto",
            # )
            pass
        except Exception as e:
            print("⚠ restore_bots lỗi:", e)


def get_bm(user: User, db: Session) -> BotManager:
    """Lấy BotManager đã tồn tại, hoặc khởi tạo mới."""
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
    user = (
        db.query(User)
        .filter(
            User.username == payload.username,
            User.password == payload.password,
        )
        .first()
    )
    if not user:
        raise HTTPException(401, "Sai username hoặc password")
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


# ==================== ACCOUNT STATUS (frontend dùng ở afterLogin) ====================
@app.get("/api/account-status")
def account_status(current: User = Depends(get_current_user)):
    """
    Frontend gọi /api/account-status để quyết định:
    - configured = True => vào Dashboard
    - configured = False => chuyển sang màn hình nhập API key
    """
    return {"configured": bool(current.api_key and current.api_secret)}


# ==================== BOT CONFIG (khớp /api/bot-config của frontend) ====================
@app.get("/api/bot-config")
def get_bot_config(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cfg = (
        db.query(BotConfig)
        .filter(BotConfig.user_id == current.id)
        .order_by(BotConfig.id.desc())
        .first()
    )
    if not cfg:
        # Config mặc định nếu chưa lưu gì
        return {
            "bot_mode": "static",
            "symbol": "BTCUSDT",
            "lev": 20,
            "percent": 5.0,
            "tp": 10.0,
            "sl": 20.0,
            "roi_trigger": None,
            "bot_count": 1,
        }

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
def save_bot_config(
    payload: BotConfigReq,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cfg = (
        db.query(BotConfig)
        .filter(BotConfig.user_id == current.id)
        .order_by(BotConfig.id.desc())
        .first()
    )
    if not cfg:
        cfg = BotConfig(user_id=current.id, bot_mode=payload.bot_mode)
        db.add(cfg)

    cfg.bot_mode = payload.bot_mode
    cfg.symbol = payload.symbol
    cfg.lev = payload.lev
    cfg.percent = payload.percent
    cfg.tp = payload.tp
    cfg.sl = payload.sl
    cfg.roi_trigger = payload.roi_trigger
    cfg.bot_count = payload.bot_count

    db.commit()
    db.refresh(cfg)
    return {"ok": True}


# ==================== BOT START / STOP / STATUS (khớp frontend) ====================
@app.post("/api/bot-start")
def bot_start(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cfg = (
        db.query(BotConfig)
        .filter(BotConfig.user_id == current.id)
        .order_by(BotConfig.id.desc())
        .first()
    )
    if not cfg:
        raise HTTPException(400, "Chưa có cấu hình bot, hãy lưu config trước")

    bm = get_bm(current, db)
    ok = bm.add_bot(
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
    if not ok:
        raise HTTPException(400, "Không thể khởi tạo bot, xem log server để biết chi tiết")
    return {"ok": True}


@app.post("/api/bot-stop")
def bot_stop(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bm = get_bm(current, db)
    # Dừng toàn bộ bot và xóa khỏi manager
    bm.stop_all()
    return {"ok": True}


@app.get("/api/bot-status")
def bot_status(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bm = BOT_MANAGERS.get(current.id)
    cfg = (
        db.query(BotConfig)
        .filter(BotConfig.user_id == current.id)
        .order_by(BotConfig.id.desc())
        .first()
    )

    if not bm or not getattr(bm, "bots", None):
        return {"running": False}

    mode = cfg.bot_mode if cfg else "unknown"
    symbol = cfg.symbol if cfg else None
    return {
        "running": True,
        "mode": mode,
        "symbol": symbol,
    }


# ==================== (TÙY CHỌN) CÁC API CŨ GIỮ LẠI NẾU MUỐN DÙNG THÊM ====================
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
def add_bot_old(
    payload: AddBotReq,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Endpoint cũ, giữ lại nếu bạn muốn quản lý nhiều bot kiểu danh sách riêng."""
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

    return {"ok": True, "id": cfg.id}


# ==================== WEBSOCKET: GIÁ & PnL ====================
@app.websocket("/ws/price")
async def ws_price(ws: WebSocket, token: Optional[str] = None, symbol: str = "BTCUSDT"):
    """
    WebSocket giá demo. Nếu muốn, bạn có thể thay bằng WebSocket Binance thật.
    Frontend đang gọi: /ws/price?token=...  (token ở đây không dùng đến).
    """
    await ws.accept()
    try:
        while True:
            price = round(50000 + random.uniform(-1000, 1000), 2)
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
    """
    WebSocket gửi số dư thực từ Binance Futures (thông qua trading_bot_lib.get_balance)
    Frontend đang gọi: /ws/pnl?token=authToken
    """
    await ws.accept()
    db: Session = SessionLocal()
    try:
        uid = TOKEN_STORE.get(token)
        if not uid:
            await ws.send_json({"error": "Token không hợp lệ hoặc đã hết hạn"})
            await ws.close(code=4001)
            return

        user = db.query(User).filter(User.id == uid).first()
        if not user or not user.api_key or not user.api_secret:
            await ws.send_json({"error": "User chưa cấu hình API Binance"})
            await ws.close(code=4002)
            return

        while True:
            bal = get_balance(user.api_key, user.api_secret)
            if bal is None:
                await ws.send_json(
                    {
                        "error": "Không lấy được số dư từ Binance",
                        "timestamp": int(time.time()),
                    }
                )
            else:
                await ws.send_json(
                    {
                        "balance": round(float(bal), 2),
                        "timestamp": int(time.time()),
                    }
                )
            # cập nhật 5 giây/lần để tránh spam API
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
