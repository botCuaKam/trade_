# trading_bot_lib_part1.py - PHẦN 1: HỆ THỐNG RSI + KHỐI LƯỢNG (LOG ĐẦY ĐỦ)
import json
import hmac
import hashlib
import time
import threading
import urllib.request
import urllib.parse
import numpy as np
import websocket
import logging
import requests
import os
import math
import traceback
import random
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import time
import ssl

# ========== BYPASS SSL VERIFICATION ==========
ssl._create_default_https_context = ssl._create_unverified_context

# ========== CẤU HÌNH LOGGING CHI TIẾT ==========
def setup_logging():
    """Cấu hình logging chi tiết để debug"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Formatter chi tiết
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )
    
    # File handler cho tất cả log
    file_handler = logging.FileHandler('bot_detailed.log', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    
    # File handler cho lỗi
    error_handler = logging.FileHandler('bot_errors.log', encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    
    # Console handler chỉ hiển thị quan trọng
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    
    # Xóa handler cũ nếu có
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Thêm handler mới
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

def log_debug(message):
    """Ghi log debug chi tiết"""
    logger.debug(f"🔧 {message}")

def log_info(message):
    """Ghi log thông tin"""
    logger.info(f"ℹ️ {message}")

def log_warning(message):
    """Ghi log cảnh báo"""
    logger.warning(f"⚠️ {message}")

def log_error(message, exc_info=None):
    """Ghi log lỗi chi tiết"""
    if exc_info:
        logger.error(f"❌ {message}", exc_info=exc_info)
    else:
        logger.error(f"❌ {message}")

def log_success(message):
    """Ghi log thành công"""
    logger.info(f"✅ {message}")

# ========== HÀM TELEGRAM ==========
def escape_html(text):
    """Escape các ký tự đặc biệt trong HTML để tránh lỗi Telegram"""
    if not text:
        return text
    return (text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;'))

def send_telegram(message, chat_id=None, reply_markup=None, bot_token=None, default_chat_id=None):
    log_debug(f"Gửi Telegram: {message[:100]}...")
    
    if not bot_token:
        log_warning("Telegram Bot Token chưa được thiết lập")
        return False
    
    chat_id = chat_id or default_chat_id
    if not chat_id:
        log_warning("Telegram Chat ID chưa được thiết lập")
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    # ESCAPE MESSAGE ĐỂ TRÁNH LỖI HTML
    safe_message = escape_html(message)
    
    payload = {
        "chat_id": chat_id,
        "text": safe_message,
        "parse_mode": "HTML"
    }
    
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    
    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            log_debug("Gửi Telegram thành công")
            return True
        else:
            log_error(f"Lỗi Telegram ({response.status_code}): {response.text}")
            return False
    except Exception as e:
        log_error(f"Lỗi kết nối Telegram: {str(e)}")
        return False

# ========== MENU TELEGRAM HOÀN CHỈNH ==========
def create_cancel_keyboard():
    return {
        "keyboard": [[{"text": "❌ Hủy bỏ"}]],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

def create_strategy_keyboard():
    return {
        "keyboard": [
            [{"text": "📊 Hệ thống RSI + Khối lượng"}],
            [{"text": "❌ Hủy bỏ"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

def create_exit_strategy_keyboard():
    return {
        "keyboard": [
            [{"text": "🎯 Chỉ TP/SL cố định"}],
            [{"text": "❌ Hủy bỏ"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

def create_bot_mode_keyboard():
    return {
        "keyboard": [
            [{"text": "🤖 Bot Tĩnh - Coin cụ thể"}, {"text": "🔄 Bot Động - Tự tìm coin"}],
            [{"text": "❌ Hủy bỏ"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

def create_symbols_keyboard(strategy=None):
    try:
        symbols = get_all_usdc_pairs(limit=12)
        if not symbols:
            symbols = ["BTCUSDC", "ETHUSDC", "BNBUSDC", "ADAUSDC", "DOGEUSDC", "XRPUSDC", "DOTUSDC", "LINKUSDC"]
    except Exception as e:
        log_error(f"Lỗi tạo symbols keyboard: {str(e)}")
        symbols = ["BTCUSDC", "ETHUSDC", "BNBUSDC", "ADAUSDC", "DOGEUSDC", "XRPUSDC", "DOTUSDC", "LINKUSDC"]
    
    keyboard = []
    row = []
    for symbol in symbols:
        row.append({"text": symbol})
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([{"text": "❌ Hủy bỏ"}])
    
    return {
        "keyboard": keyboard,
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

def create_main_menu():
    return {
        "keyboard": [
            [{"text": "📊 Danh sách Bot"}, {"text": "📊 Thống kê"}],
            [{"text": "➕ Thêm Bot"}, {"text": "⛔ Dừng Bot"}],
            [{"text": "💰 Số dư"}, {"text": "📈 Vị thế"}],
            [{"text": "⚙️ Cấu hình"}, {"text": "🎯 Chiến lược"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def create_leverage_keyboard(strategy=None):
    leverages = ["3", "5", "10", "15", "20", "25", "50", "75", "100"]
    
    keyboard = []
    row = []
    for lev in leverages:
        row.append({"text": f"{lev}x"})
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([{"text": "❌ Hủy bỏ"}])
    
    return {
        "keyboard": keyboard,
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

def create_percent_keyboard():
    return {
        "keyboard": [
            [{"text": "1"}, {"text": "3"}, {"text": "5"}, {"text": "10"}],
            [{"text": "15"}, {"text": "20"}, {"text": "25"}, {"text": "50"}],
            [{"text": "❌ Hủy bỏ"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

def create_tp_keyboard():
    return {
        "keyboard": [
            [{"text": "50"}, {"text": "100"}, {"text": "200"}],
            [{"text": "300"}, {"text": "500"}, {"text": "1000"}],
            [{"text": "❌ Hủy bỏ"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

def create_sl_keyboard():
    return {
        "keyboard": [
            [{"text": "0"}, {"text": "50"}, {"text": "100"}],
            [{"text": "150"}, {"text": "200"}, {"text": "500"}],
            [{"text": "❌ Hủy bỏ"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

def create_bot_count_keyboard():
    return {
        "keyboard": [
            [{"text": "1"}, {"text": "2"}, {"text": "3"}],
            [{"text": "5"}, {"text": "10"}],
            [{"text": "❌ Hủy bỏ"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

def create_roi_trigger_keyboard():
    return {
        "keyboard": [
            [{"text": "30"}, {"text": "50"}, {"text": "100"}],
            [{"text": "150"}, {"text": "200"}, {"text": "300"}],
            [{"text": "❌ Tắt tính năng"}],
            [{"text": "❌ Hủy bỏ"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True
    }

# ========== API BINANCE - LOG CHI TIẾT ==========
def sign(query, api_secret):
    try:
        log_debug(f"Ký dữ liệu: {query[:50]}...")
        signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        log_debug(f"Chữ ký tạo thành công: {signature[:20]}...")
        return signature
    except Exception as e:
        log_error(f"Lỗi tạo chữ ký: {str(e)}")
        return ""

def binance_api_request(url, method='GET', params=None, headers=None):
    log_debug(f"API Request: {method} {url}")
    if params:
        log_debug(f"API Params: {params}")
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Thêm User-Agent để tránh bị chặn
            if headers is None:
                headers = {}
            
            if 'User-Agent' not in headers:
                headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            
            if method.upper() == 'GET':
                if params:
                    query = urllib.parse.urlencode(params)
                    url_with_params = f"{url}?{query}"
                    log_debug(f"URL với params: {url_with_params}")
                    req = urllib.request.Request(url_with_params, headers=headers)
                else:
                    req = urllib.request.Request(url, headers=headers)
            else:
                data = urllib.parse.urlencode(params).encode() if params else None
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                log_debug(f"POST data: {data}")
            
            # Tăng timeout và thêm retry logic
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status == 200:
                    result = json.loads(response.read().decode())
                    log_debug(f"API Response thành công: {str(result)[:200]}...")
                    return result
                else:
                    error_content = response.read().decode()
                    log_error(f"Lỗi API ({response.status}): {error_content}")
                    if response.status == 401:
                        return None
                    if response.status == 429:
                        sleep_time = 2 ** attempt
                        log_warning(f"Rate limit, chờ {sleep_time}s")
                        time.sleep(sleep_time)
                    elif response.status >= 500:
                        time.sleep(1)
                    continue
                    
        except urllib.error.HTTPError as e:
            if e.code == 451:
                log_error("❌ Lỗi 451: Truy cập bị chặn - Có thể do hạn chế địa lý. Vui lòng kiểm tra VPN/proxy.")
                # Thử sử dụng endpoint thay thế
                if "fapi.binance.com" in url:
                    new_url = url.replace("fapi.binance.com", "fapi.binance.com")
                    log_info(f"Thử URL thay thế: {new_url}")
                return None
            else:
                log_error(f"Lỗi HTTP ({e.code}): {e.reason}")
            
            if e.code == 401:
                return None
            if e.code == 429:
                sleep_time = 2 ** attempt
                log_warning(f"Rate limit, chờ {sleep_time}s")
                time.sleep(sleep_time)
            elif e.code >= 500:
                time.sleep(1)
            continue
                
        except Exception as e:
            log_error(f"Lỗi kết nối API (lần {attempt + 1}): {str(e)}")
            time.sleep(1)
    
    log_error(f"Không thể thực hiện yêu cầu API sau {max_retries} lần thử")
    return None

def get_all_usdc_pairs(limit=100):
    log_info(f"Lấy danh sách {limit} coin USDC...")
    try:
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        data = binance_api_request(url)
        if not data:
            log_warning("Không lấy được dữ liệu từ Binance, trả về danh sách rỗng")
            return []
        
        usdc_pairs = []
        for symbol_info in data.get('symbols', []):
            symbol = symbol_info.get('symbol', '')
            if symbol.endswith('USDC') and symbol_info.get('status') == 'TRADING':
                usdc_pairs.append(symbol)
        
        log_success(f"Lấy được {len(usdc_pairs)} coin USDC từ Binance")
        return usdc_pairs[:limit] if limit else usdc_pairs
        
    except Exception as e:
        log_error(f"Lỗi lấy danh sách coin từ Binance: {str(e)}")
        return []

def get_top_volume_symbols(limit=100):
    """Top {limit} USDC pairs theo quoteVolume của NẾN 1M đã đóng (đa luồng)."""
    log_info(f"Lấy top {limit} coin theo volume...")
    try:
        universe = get_all_usdc_pairs(limit=100) or []
        if not universe:
            log_warning("❌ Không lấy được danh sách coin USDC")
            return []

        scored, failed = [], 0
        max_workers = 8
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futmap = {ex.submit(_last_closed_1m_quote_volume, s): s for s in universe}
            for fut in as_completed(futmap):
                sym = futmap[fut]
                try:
                    qv = fut.result()
                    if qv is not None:
                        scored.append((sym, qv))
                except Exception as e:
                    failed += 1
                    log_error(f"Lỗi lấy volume {sym}: {str(e)}")
                time.sleep(0.5)

        scored.sort(key=lambda x: x[1], reverse=True)
        top_syms = [s for s, _ in scored[:limit]]
        log_success(f"Top {len(top_syms)} theo 1m quoteVolume (phân tích: {len(scored)}, lỗi: {failed})")
        return top_syms

    except Exception as e:
        log_error(f"Lỗi lấy top volume 1 phút (đa luồng): {str(e)}")
        return []

def get_max_leverage(symbol, api_key, api_secret):
    """Lấy đòn bẩy tối đa cho một symbol"""
    log_debug(f"Lấy đòn bẩy tối đa cho {symbol}")
    try:
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        data = binance_api_request(url)
        if not data:
            return 100
        
        for s in data['symbols']:
            if s['symbol'] == symbol.upper():
                for f in s['filters']:
                    if f['filterType'] == 'LEVERAGE':
                        if 'maxLeverage' in f:
                            max_leverage = int(f['maxLeverage'])
                            log_debug(f"Đòn bẩy tối đa {symbol}: {max_leverage}x")
                            return max_leverage
                break
        return 100
    except Exception as e:
        log_error(f"Lỗi lấy đòn bẩy tối đa {symbol}: {str(e)}")
        return 100

def get_step_size(symbol, api_key, api_secret):
    if not symbol:
        log_error("❌ Lỗi: Symbol là None khi lấy step size")
        return 0.001
    
    log_debug(f"Lấy step size cho {symbol}")
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        data = binance_api_request(url)
        if not data:
            return 0.001
        for s in data['symbols']:
            if s['symbol'] == symbol.upper():
                for f in s['filters']:
                    if f['filterType'] == 'LOT_SIZE':
                        step_size = float(f['stepSize'])
                        log_debug(f"Step size {symbol}: {step_size}")
                        return step_size
    except Exception as e:
        log_error(f"Lỗi lấy step size: {str(e)}")
    return 0.001

def set_leverage(symbol, lev, api_key, api_secret):
    if not symbol:
        log_error("❌ Lỗi: Symbol là None khi set leverage")
        return False
    
    log_info(f"Thiết lập đòn bẩy {symbol} -> {lev}x")
    try:
        ts = int(time.time() * 1000)
        params = {
            "symbol": symbol.upper(),
            "leverage": lev,
            "timestamp": ts
        }
        query = urllib.parse.urlencode(params)
        sig = sign(query, api_secret)
        url = f"https://fapi.binance.com/fapi/v1/leverage?{query}&signature={sig}"
        headers = {'X-MBX-APIKEY': api_key}
        
        response = binance_api_request(url, method='POST', headers=headers)
        if response is None:
            log_error(f"Không thể thiết lập đòn bẩy {symbol}")
            return False
        if response and 'leverage' in response:
            log_success(f"Đã thiết lập đòn bẩy {symbol} -> {lev}x")
            return True
        log_error(f"Thiết lập đòn bẩy thất bại: {response}")
        return False
    except Exception as e:
        log_error(f"Lỗi thiết lập đòn bẩy: {str(e)}")
        return False

def get_balance(api_key, api_secret):
    """Lấy số dư KHẢ DỤNG (availableBalance) để tính toán khối lượng"""
    log_debug("Lấy số dư từ Binance...")
    try:
        ts = int(time.time() * 1000)
        params = {"timestamp": ts}
        query = urllib.parse.urlencode(params)
        sig = sign(query, api_secret)
        url = f"https://fapi.binance.com/fapi/v2/account?{query}&signature={sig}"
        headers = {'X-MBX-APIKEY': api_key}
        
        data = binance_api_request(url, headers=headers)
        if not data:
            log_error("❌ Không lấy được số dư từ Binance")
            return None
            
        for asset in data['assets']:
            if asset['asset'] == 'USDC':
                available_balance = float(asset['availableBalance'])
                total_balance = float(asset['walletBalance'])
                
                log_info(f"Số dư - Khả dụng: {available_balance:.2f} USDC, Tổng: {total_balance:.2f} USDC")
                return available_balance
        log_warning("Không tìm thấy số dư USDC")
        return 0
    except Exception as e:
        log_error(f"Lỗi lấy số dư: {str(e)}")
        return None

def place_order(symbol, side, qty, api_key, api_secret):
    if not symbol:
        log_error("❌ Không thể đặt lệnh: symbol là None")
        return None
    
    log_info(f"Đặt lệnh {side} {symbol} khối lượng {qty}")
    try:
        ts = int(time.time() * 1000)
        params = {
            "symbol": symbol.upper(),
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "timestamp": ts
        }
        query = urllib.parse.urlencode(params)
        sig = sign(query, api_secret)
        url = f"https://fapi.binance.com/fapi/v1/order?{query}&signature={sig}"
        headers = {'X-MBX-APIKEY': api_key}
        
        result = binance_api_request(url, method='POST', headers=headers)
        if result:
            log_success(f"Đặt lệnh thành công: {side} {symbol} {qty}")
        else:
            log_error(f"Đặt lệnh thất bại: {side} {symbol} {qty}")
        return result
    except Exception as e:
        log_error(f"Lỗi đặt lệnh: {str(e)}")
    return None

def cancel_all_orders(symbol, api_key, api_secret):
    if not symbol:
        log_error("❌ Không thể hủy lệnh: symbol là None")
        return False
    
    log_info(f"Hủy tất cả lệnh {symbol}")
    try:
        ts = int(time.time() * 1000)
        params = {"symbol": symbol.upper(), "timestamp": ts}
        query = urllib.parse.urlencode(params)
        sig = sign(query, api_secret)
        url = f"https://fapi.binance.com/fapi/v1/allOpenOrders?{query}&signature={sig}"
        headers = {'X-MBX-APIKEY': api_key}
        
        binance_api_request(url, method='DELETE', headers=headers)
        log_success(f"Đã hủy tất cả lệnh {symbol}")
        return True
    except Exception as e:
        log_error(f"Lỗi hủy lệnh: {str(e)}")
    return False

def get_current_price(symbol):
    if not symbol:
        log_error("💰 Lỗi: Symbol là None khi lấy giá")
        return 0
    
    log_debug(f"Lấy giá hiện tại {symbol}")
    try:
        url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol.upper()}"
        data = binance_api_request(url)
        if data and 'price' in data:
            price = float(data['price'])
            if price > 0:
                log_debug(f"Giá {symbol}: {price}")
                return price
            else:
                log_error(f"💰 Giá {symbol} = 0")
        return 0
    except Exception as e:
        log_error(f"💰 Lỗi lấy giá {symbol}: {str(e)}")
    return 0

def get_positions(symbol=None, api_key=None, api_secret=None):
    log_debug(f"Lấy vị thế {symbol if symbol else 'tất cả'}")
    try:
        ts = int(time.time() * 1000)
        params = {"timestamp": ts}
        if symbol:
            params["symbol"] = symbol.upper()
        query = urllib.parse.urlencode(params)
        sig = sign(query, api_secret)
        url = f"https://fapi.binance.com/fapi/v2/positionRisk?{query}&signature={sig}"
        headers = {'X-MBX-APIKEY': api_key}
        
        positions = binance_api_request(url, headers=headers)
        if not positions:
            log_debug("Không có vị thế nào")
            return []
        
        log_debug(f"Lấy được {len(positions)} vị thế")
        if symbol:
            for pos in positions:
                if pos['symbol'] == symbol.upper():
                    return [pos]
        return positions
    except Exception as e:
        log_error(f"Lỗi lấy vị thế: {str(e)}")
    return []

# ========== COIN MANAGER ==========
class CoinManager:
    def __init__(self):
        self.active_coins = set()
        self._lock = threading.Lock()
        log_info("Khởi tạo CoinManager")
    
    def register_coin(self, symbol):
        if not symbol:
            return
        with self._lock:
            self.active_coins.add(symbol.upper())
            log_debug(f"Đăng ký coin: {symbol.upper()}")
    
    def unregister_coin(self, symbol):
        if not symbol:
            return
        with self._lock:
            self.active_coins.discard(symbol.upper())
            log_debug(f"Hủy đăng ký coin: {symbol.upper()}")
    
    def is_coin_active(self, symbol):
        if not symbol:
            return False
        with self._lock:
            is_active = symbol.upper() in self.active_coins
            log_debug(f"Kiểm tra coin {symbol}: {'active' if is_active else 'inactive'}")
            return is_active
    
    def get_active_coins(self):
        with self._lock:
            active_list = list(self.active_coins)
            log_debug(f"Danh sách coin active: {active_list}")
            return active_list

# ========== SMART COIN FINDER VỚI HỆ THỐNG RSI + KHỐI LƯỢNG MỚI ==========
class SmartCoinFinder:
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        log_info("Khởi tạo SmartCoinFinder")
        
    def get_symbol_leverage(self, symbol):
        """Lấy đòn bẩy tối đa của symbol"""
        leverage = get_max_leverage(symbol, self.api_key, self.api_secret)
        log_debug(f"Đòn bẩy {symbol}: {leverage}x")
        return leverage
    
    def calculate_rsi(self, prices, period=14):
        """Tính RSI từ danh sách giá"""
        log_debug(f"Tính RSI từ {len(prices)} giá, period={period}")
        if len(prices) < period + 1:
            log_warning(f"Không đủ dữ liệu để tính RSI: {len(prices)} < {period + 1}")
            return 50  # Giá trị trung bình nếu không đủ dữ liệu
            
        try:
            deltas = np.diff(prices)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            
            avg_gains = np.mean(gains[:period])
            avg_losses = np.mean(losses[:period])
            
            if avg_losses == 0:
                log_debug("Avg losses = 0, RSI = 100")
                return 100
                
            rs = avg_gains / avg_losses
            rsi = 100 - (100 / (1 + rs))
            
            log_debug(f"RSI tính được: {rsi:.2f}")
            return rsi
            
        except Exception as e:
            log_error(f"Lỗi tính RSI: {str(e)}")
            return 50
    
    def get_rsi_signal(self, symbol, volume_threshold=20):
        """Phân tích tín hiệu RSI và khối lượng - LOGIC MỚI"""
        log_debug(f"Phân tích tín hiệu RSI {symbol}, volume_threshold={volume_threshold}")
        try:
            # Lấy dữ liệu kline 5 phút
            data = binance_api_request(
                "https://fapi.binance.com/fapi/v1/klines",
                params={"symbol": symbol, "interval": "5m", "limit": 15}
            )
            if not data or len(data) < 15:
                log_warning(f"Không đủ dữ liệu kline cho {symbol}")
                return None
            
            # Lấy 3 nến gần nhất
            prev_candle = data[-3]  # Nến trước
            current_candle = data[-2]  # Nến hiện tại (đã đóng)
            latest_candle = data[-1]  # Nến mới nhất (có thể chưa đóng)
            
            # Giá đóng cửa và RSI
            closes = [float(k[4]) for k in data]
            rsi_current = self.calculate_rsi(closes)
            
            # So sánh giá và khối lượng
            prev_close = float(prev_candle[4])
            current_close = float(current_candle[4])
            latest_close = float(latest_candle[4]) if len(latest_candle) > 4 else current_close
            
            prev_volume = float(prev_candle[5])
            current_volume = float(current_candle[5])
            
            # Xác định xu hướng giá
            price_increase = current_close > prev_close
            price_decrease = current_close < prev_close
            
            # Xác định xu hướng khối lượng
            volume_increase = current_volume > prev_volume * (1 + volume_threshold/100)
            volume_decrease = current_volume < prev_volume * (1 - volume_threshold/100)
            
            log_debug(f"{symbol} - RSI: {rsi_current:.2f}, Giá: {prev_close:.4f}->{current_close:.4f} ({'↑' if price_increase else '↓' if price_decrease else '→'}), "
                     f"Volume: {prev_volume:.0f}->{current_volume:.0f} ({'↑' if volume_increase else '↓' if volume_decrease else '→'})")
            
            # LOGIC RSI MỚI THEO YÊU CẦU
            if rsi_current > 80:
                if price_increase and volume_increase:
                    log_info(f"{symbol} - RSI > 80, giá tăng, volume tăng -> SELL")
                    return "SELL"
                elif price_increase and volume_decrease:
                    log_info(f"{symbol} - RSI > 80, giá tăng, volume giảm -> BUY")
                    return "BUY"
                    
            elif rsi_current < 20:
                if price_decrease and volume_decrease:
                    log_info(f"{symbol} - RSI < 20, giá giảm, volume giảm -> SELL")
                    return "SELL"
                elif price_decrease and volume_increase:
                    log_info(f"{symbol} - RSI < 20, giá giảm, volume tăng -> BUY")
                    return "BUY"
            
            # ĐIỀU KIỆN BỔ SUNG
            elif rsi_current > 20 and not price_decrease and volume_decrease:
                log_info(f"{symbol} - RSI > 20, giá không giảm, volume giảm -> BUY")
                return "BUY"
                
            elif rsi_current < 80 and not price_increase and volume_increase:
                log_info(f"{symbol} - RSI < 80, giá không tăng, volume tăng -> SELL")
                return "SELL"
            
            log_debug(f"{symbol} - Không có tín hiệu phù hợp")
            return None
            
        except Exception as e:
            log_error(f"Lỗi phân tích RSI {symbol}: {str(e)}")
            return None
    
    def get_entry_signal(self, symbol):
        """Tín hiệu vào lệnh - khối lượng 20%"""
        log_debug(f"Lấy tín hiệu vào lệnh {symbol}")
        signal = self.get_rsi_signal(symbol, volume_threshold=20)
        log_info(f"Tín hiệu vào lệnh {symbol}: {signal}")
        return signal
    
    def get_exit_signal(self, symbol):
        """Tín hiệu đóng lệnh - khối lượng 40%"""
        log_debug(f"Lấy tín hiệu đóng lệnh {symbol}")
        signal = self.get_rsi_signal(symbol, volume_threshold=40)
        log_info(f"Tín hiệu đóng lệnh {symbol}: {signal}")
        return signal
    
    def has_existing_position(self, symbol):
        """Kiểm tra xem coin đã có vị thế trên Binance chưa"""
        log_debug(f"Kiểm tra vị thế hiện có {symbol}")
        try:
            positions = get_positions(symbol, self.api_key, self.api_secret)
            if positions:
                for pos in positions:
                    position_amt = float(pos.get('positionAmt', 0))
                    if abs(position_amt) > 0:
                        log_info(f"⚠️ Phát hiện vị thế trên {symbol}: {position_amt}")
                        return True
            log_debug(f"Không có vị thế trên {symbol}")
            return False
        except Exception as e:
            log_error(f"❌ Lỗi kiểm tra vị thế {symbol}: {str(e)}")
            return True  # Trả về True để an toàn
    
    def find_best_coin(self, target_direction, excluded_coins=None, required_leverage=10):
        """Tìm coin tốt nhất - MỖI COIN ĐỘC LẬP"""
        log_info(f"Tìm coin tốt nhất - Hướng: {target_direction}, Đòn bẩy tối thiểu: {required_leverage}x")
        try:
            all_symbols = get_all_usdc_pairs(limit=50)
            if not all_symbols:
                log_warning("Không có symbol nào để tìm kiếm")
                return None
            
            valid_symbols = []
            
            for symbol in all_symbols:
                # Kiểm tra coin đã bị loại trừ
                if excluded_coins and symbol in excluded_coins:
                    log_debug(f"Bỏ qua {symbol} - đã bị loại trừ")
                    continue
                
                # 🔴 QUAN TRỌNG: Kiểm tra coin đã có vị thế trên Binance
                if self.has_existing_position(symbol):
                    log_info(f"🚫 Bỏ qua {symbol} - đã có vị thế trên Binance")
                    continue
                
                # Kiểm tra đòn bẩy
                max_lev = self.get_symbol_leverage(symbol)
                if max_lev < required_leverage:
                    log_debug(f"Bỏ qua {symbol} - đòn bẩy không đủ: {max_lev}x < {required_leverage}x")
                    continue
                
                # 🔴 SỬ DỤNG TÍN HIỆU VÀO LỆNH (20% khối lượng)
                entry_signal = self.get_entry_signal(symbol)
                if entry_signal == target_direction:
                    valid_symbols.append(symbol)
                    log_info(f"✅ Tìm thấy coin phù hợp: {symbol} - Tín hiệu: {entry_signal}")
                else:
                    log_debug(f"🔄 Bỏ qua {symbol} - Tín hiệu: {entry_signal} (không trùng với {target_direction})")
            
            if not valid_symbols:
                log_info(f"❌ Không tìm thấy coin nào có tín hiệu trùng với {target_direction}")
                return None
            
            # Chọn ngẫu nhiên từ danh sách hợp lệ
            selected_symbol = random.choice(valid_symbols)
            max_lev = self.get_symbol_leverage(selected_symbol)
            
            # 🔴 KIỂM TRA LẦN CUỐI: Đảm bảo coin được chọn không có vị thế
            if self.has_existing_position(selected_symbol):
                log_info(f"🚫 {selected_symbol} - Coin được chọn đã có vị thế, bỏ qua")
                return None
            
            log_success(f"Đã chọn coin: {selected_symbol} - Tín hiệu: {target_direction} - Đòn bẩy: {max_lev}x")
            return selected_symbol
            
        except Exception as e:
            log_error(f"❌ Lỗi tìm coin: {str(e)}")
            return None

# ========== WEBSOCKET MANAGER ==========
class WebSocketManager:
    def __init__(self):
        self.connections = {}
        self.executor = ThreadPoolExecutor(max_workers=10)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        log_info("Khởi tạo WebSocketManager")
        
    def add_symbol(self, symbol, callback):
        if not symbol:
            log_error("Không thể thêm symbol None vào WebSocket")
            return
            
        symbol = symbol.upper()
        log_info(f"Thêm symbol vào WebSocket: {symbol}")
        with self._lock:
            if symbol not in self.connections:
                self._create_connection(symbol, callback)
                
    def _create_connection(self, symbol, callback):
        if self._stop_event.is_set():
            log_warning("WebSocketManager đã dừng, không tạo kết nối mới")
            return
            
        stream = f"{symbol.lower()}@trade"
        url = f"wss://fstream.binance.com/ws/{stream}"
        log_info(f"Tạo WebSocket connection: {url}")
        
        def on_message(ws, message):
            try:
                data = json.loads(message)
                if 'p' in data:
                    price = float(data['p'])
                    log_debug(f"WebSocket {symbol} price: {price}")
                    self.executor.submit(callback, price)
            except Exception as e:
                log_error(f"Lỗi xử lý tin nhắn WebSocket {symbol}: {str(e)}")
                
        def on_error(ws, error):
            log_error(f"Lỗi WebSocket {symbol}: {str(error)}")
            if not self._stop_event.is_set():
                log_info(f"WebSocket {symbol} sẽ kết nối lại sau 5s")
                time.sleep(5)
                self._reconnect(symbol, callback)
            
        def on_close(ws, close_status_code, close_msg):
            log_info(f"WebSocket đóng {symbol}: {close_status_code} - {close_msg}")
            if not self._stop_event.is_set() and symbol in self.connections:
                log_info(f"WebSocket {symbol} sẽ kết nối lại sau 5s")
                time.sleep(5)
                self._reconnect(symbol, callback)
                
        ws = websocket.WebSocketApp(
            url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        
        thread = threading.Thread(target=ws.run_forever, daemon=True)
        thread.start()
        
        self.connections[symbol] = {
            'ws': ws,
            'thread': thread,
            'callback': callback
        }
        log_success(f"WebSocket bắt đầu cho {symbol}")
        
    def _reconnect(self, symbol, callback):
        log_info(f"Kết nối lại WebSocket cho {symbol}")
        self.remove_symbol(symbol)
        self._create_connection(symbol, callback)
        
    def remove_symbol(self, symbol):
        if not symbol:
            return
            
        symbol = symbol.upper()
        log_info(f"Xóa WebSocket cho {symbol}")
        with self._lock:
            if symbol in self.connections:
                try:
                    self.connections[symbol]['ws'].close()
                    log_debug(f"Đã đóng WebSocket {symbol}")
                except Exception as e:
                    log_error(f"Lỗi đóng WebSocket {symbol}: {str(e)}")
                del self.connections[symbol]
                log_success(f"WebSocket đã xóa cho {symbol}")
                
    def stop(self):
        log_info("Dừng WebSocketManager")
        self._stop_event.set()
        symbols = list(self.connections.keys())
        for symbol in symbols:
            self.remove_symbol(symbol)
        log_success("WebSocketManager đã dừng")

# ========== BASE BOT VỚI LOG CHI TIẾT ==========
class BaseBot:
    def __init__(self, symbol, lev, percent, tp, sl, roi_trigger, ws_manager, api_key, api_secret,
                 telegram_bot_token, telegram_chat_id, strategy_name, config_key=None, bot_id=None,
                 coin_manager=None, symbol_locks=None, max_coins=1):

        self.max_coins = max_coins
        self.active_symbols = []
        self.symbol_data = {}
        self.symbol = symbol.upper() if symbol else None
        
        self.lev = lev
        self.percent = percent
        self.tp = tp
        self.sl = sl
        self.roi_trigger = roi_trigger
        self.ws_manager = ws_manager
        self.api_key = api_key
        self.api_secret = api_secret
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.strategy_name = strategy_name
        self.config_key = config_key
        self.bot_id = bot_id or f"{strategy_name}_{int(time.time())}_{random.randint(1000, 9999)}"

        # 🔴 SỬA: Luôn ở trạng thái "searching" để tìm coin ngay lập tức
        self.status = "searching"
        self._stop = False

        # 🔴 THÊM: Biến để quản lý tuần tự
        self.current_processing_symbol = None
        self.last_trade_completion_time = 0
        self.trade_cooldown = 3  # Chờ 3s sau mỗi lệnh

        # Quản lý thời gian
        self.last_global_position_check = 0
        self.last_error_log_time = 0
        self.global_position_check_interval = 10

        # Thống kê
        self.global_long_count = 0
        self.global_short_count = 0
        self.global_long_pnl = 0
        self.global_short_pnl = 0

        self.coin_manager = coin_manager or CoinManager()
        self.symbol_locks = symbol_locks
        self.coin_finder = SmartCoinFinder(api_key, api_secret)

        self.find_new_bot_after_close = True
        self.bot_creation_time = time.time()

        # 🔴 THÊM: Lock để đảm bảo thread-safe khi thêm/xóa coin
        self.symbol_management_lock = threading.Lock()

        log_info(f"Khởi tạo bot {self.bot_id}: symbol={symbol}, lev={lev}, percent={percent}, "
                f"tp={tp}, sl={sl}, roi_trigger={roi_trigger}, max_coins={max_coins}")

        # Khởi tạo symbol đầu tiên nếu có
        if symbol and not self.coin_finder.has_existing_position(symbol):
            log_info(f"Thêm symbol khởi tạo: {symbol}")
            self._add_symbol(symbol)
        
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

        roi_info = f" | 🎯 ROI Trigger: {roi_trigger}%" if roi_trigger else " | 🎯 ROI Trigger: Tắt"
        message = f"🟢 Bot {strategy_name} khởi động | Tối đa: {max_coins} coin | ĐB: {lev}x | Vốn: {percent}% | TP/SL: {tp}%/{sl}%{roi_info}"
        self.log(message)

    def _run(self):
        """Vòng lặp chính - XỬ LÝ NỐI TIẾP với HỆ THỐNG RSI MỚI - ĐÃ SỬA"""
        log_info(f"Bot {self.bot_id} bắt đầu vòng lặp chính")
        while not self._stop:
            try:
                current_time = time.time()
                
                # KIỂM TRA VỊ THẾ TOÀN TÀI KHOẢN ĐỊNH KỲ
                if current_time - self.last_global_position_check > self.global_position_check_interval:
                    log_debug("Kiểm tra vị thế toàn tài khoản")
                    self.check_global_positions()
                    self.last_global_position_check = current_time
                
                # 🔴 QUAN TRỌNG: KIỂM TRA COOLDOWN TRƯỚC KHI XỬ LÝ COIN TIẾP THEO
                if current_time - self.last_trade_completion_time < self.trade_cooldown:
                    log_debug(f"Đang trong cooldown, chờ thêm {self.trade_cooldown - (current_time - self.last_trade_completion_time):.1f}s")
                    time.sleep(0.5)
                    continue
                
                # 🔴 SỬA: LUÔN TÌM COIN MỚI NẾU CHƯA ĐẠT GIỚI HẠN - KHÔNG CẦN CHỜ ĐỦ
                if len(self.active_symbols) < self.max_coins:
                    log_info(f"Tìm coin mới: {len(self.active_symbols)}/{self.max_coins}")
                    if self._find_and_add_new_coin():
                        self.last_trade_completion_time = current_time
                        time.sleep(3)
                        continue
                    else:
                        # Nếu không tìm được coin mới, vẫn tiếp tục xử lý coin hiện có
                        log_debug("Không tìm được coin mới, tiếp tục xử lý coin hiện có")
                        pass
                
                # 🔴 XỬ LÝ NỐI TIẾP: Chỉ xử lý 1 coin tại 1 thời điểm
                if self.active_symbols:
                    # Lấy coin đầu tiên trong danh sách để xử lý
                    symbol_to_process = self.active_symbols[0]
                    self.current_processing_symbol = symbol_to_process
                    
                    log_debug(f"Xử lý coin: {symbol_to_process}")
                    # Xử lý coin này - BAO GỒM CẢ TP/SL VÀ NHỒI LỆNH
                    trade_executed = self._process_single_symbol(symbol_to_process)
                    
                    # 🔴 QUAN TRỌNG: GỌI CÁC HÀM KIỂM TRA TP/SL VÀ NHỒI LỆNH CHO TẤT CẢ COIN
                    # Đảm bảo tất cả coin đều được kiểm tra TP/SL và nhồi lệnh
                    for symbol in self.active_symbols:
                        if symbol != symbol_to_process:  # Coin đang xử lý đã được kiểm tra trong _process_single_symbol
                            self._check_symbol_tp_sl(symbol)
                            self._check_symbol_averaging_down(symbol)
                    
                    # 🔴 CHỜ 3s SAU KHI XỬ LÝ XONG
                    self.last_trade_completion_time = time.time()
                    time.sleep(3)
                    
                    # Xoay danh sách: chuyển coin vừa xử lý xuống cuối
                    if len(self.active_symbols) > 1:
                        self.active_symbols.append(self.active_symbols.pop(0))
                        log_debug(f"Xoay danh sách coin: {self.active_symbols}")
                    
                    self.current_processing_symbol = None
                else:
                    # Không có coin nào, chờ và thử tìm lại
                    log_debug("Không có coin nào, chờ 5s")
                    time.sleep(5)
                
            except Exception as e:
                if time.time() - self.last_error_log_time > 10:
                    log_error(f"Lỗi hệ thống: {str(e)}", exc_info=True)
                    self.last_error_log_time = time.time()
                time.sleep(1)

    def _process_single_symbol(self, symbol):
        """Xử lý một symbol duy nhất - HỆ THỐNG RSI + KHỐI LƯỢNG MỚI - ĐÃ SỬA ĐỂ BAO GỒM TP/SL"""
        log_debug(f"Xử lý symbol {symbol}")
        try:
            symbol_info = self.symbol_data[symbol]
            current_time = time.time()
            
            # Kiểm tra vị thế định kỳ
            if current_time - symbol_info.get('last_position_check', 0) > 30:
                log_debug(f"Kiểm tra vị thế {symbol}")
                self._check_symbol_position(symbol)
                symbol_info['last_position_check'] = current_time
            
            # 🔴 KIỂM TRA BỔ SUNG: Đảm bảo coin không có vị thế trên Binance
            if self.coin_finder.has_existing_position(symbol) and not symbol_info['position_open']:
                log_warning(f"{symbol} - PHÁT HIỆN CÓ VỊ THẾ TRÊN BINANCE, DỪNG THEO DÕI VÀ TÌM COIN KHÁC")
                self.stop_symbol(symbol)
                return False
            
            # Xử lý theo trạng thái
            if symbol_info['position_open']:
                log_debug(f"{symbol} - Đang có vị thế mở")
                # 🔴 KIỂM TRA ĐÓNG LỆNH THÔNG MINH (ROI + TÍN HIỆU 40%)
                if self._check_smart_exit_condition(symbol):
                    return True
                
                # 🔴 KIỂM TRA TP/SL TRUYỀN THỐNG
                self._check_symbol_tp_sl(symbol)
                
                # 🔴 KIỂM TRA NHỒI LỆNH
                self._check_symbol_averaging_down(symbol)
            else:
                log_debug(f"{symbol} - Chưa có vị thế, tìm cơ hội vào lệnh")
                # Tìm cơ hội vào lệnh - CHỈ KHI ĐỦ THỜI GIAN CHỜ
                if (current_time - symbol_info['last_trade_time'] > 60 and 
                    current_time - symbol_info['last_close_time'] > 3600):
                    
                    target_side = self.get_next_side_based_on_comprehensive_analysis()
                    log_debug(f"{symbol} - Hướng lệnh mục tiêu: {target_side}")
                    
                    # 🔴 SỬ DỤNG TÍN HIỆU VÀO LỆNH MỚI (20% khối lượng)
                    entry_signal = self.coin_finder.get_entry_signal(symbol)
                    log_debug(f"{symbol} - Tín hiệu vào lệnh: {entry_signal}")
                    
                    if entry_signal == target_side:
                        # 🔴 KIỂM TRA CUỐI CÙNG TRƯỚC KHI VÀO LỆNH
                        if self.coin_finder.has_existing_position(symbol):
                            log_warning(f"{symbol} - ĐÃ CÓ VỊ THẾ TRÊN BINANCE, BỎ QUA VÀ TÌM COIN KHÁC")
                            self.stop_symbol(symbol)
                            return False
                        
                        if self._open_symbol_position(symbol, target_side):
                            symbol_info['last_trade_time'] = current_time
                            return True
            
            return False
            
        except Exception as e:
            log_error(f"Lỗi xử lý {symbol}: {str(e)}", exc_info=True)
            return False

    def _check_smart_exit_condition(self, symbol):
        """Kiểm tra điều kiện đóng lệnh thông minh - GIỐNG HỆT ĐIỀU KIỆN VÀO LỆNH"""
        log_debug(f"Kiểm tra điều kiện đóng lệnh thông minh {symbol}")
        try:
            if not self.symbol_data[symbol]['position_open']:
                return False
            
            # Chỉ kiểm tra nếu đã kích hoạt ROI trigger
            if not self.symbol_data[symbol]['roi_check_activated']:
                log_debug(f"{symbol} - ROI trigger chưa kích hoạt")
                return False
            
            current_price = get_current_price(symbol)
            if current_price <= 0:
                return False
            
            # Tính ROI hiện tại
            if self.symbol_data[symbol]['side'] == "BUY":
                profit = (current_price - self.symbol_data[symbol]['entry']) * abs(self.symbol_data[symbol]['qty'])
            else:
                profit = (self.symbol_data[symbol]['entry'] - current_price) * abs(self.symbol_data[symbol]['qty'])
                
            invested = self.symbol_data[symbol]['entry'] * abs(self.symbol_data[symbol]['qty']) / self.lev
            if invested <= 0:
                return False
                
            current_roi = (profit / invested) * 100
            log_debug(f"{symbol} - ROI hiện tại: {current_roi:.2f}%")
            
            # Kiểm tra nếu đạt ROI trigger
            if current_roi >= self.roi_trigger:
                # 🔴 SỬ DỤNG TÍN HIỆU ĐÓNG LỆNH (40% khối lượng) - GIỐNG HỆT ĐIỀU KIỆN VÀO LỆNH
                exit_signal = self.coin_finder.get_exit_signal(symbol)
                log_debug(f"{symbol} - Tín hiệu đóng lệnh: {exit_signal}")
                
                if exit_signal:
                    reason = f"🎯 Đạt ROI {self.roi_trigger}% + Tín hiệu đóng lệnh (ROI: {current_roi:.2f}%)"
                    log_info(f"{symbol} - Điều kiện đóng lệnh thông minh: {reason}")
                    self._close_symbol_position(symbol, reason)
                    return True
            
            return False
            
        except Exception as e:
            log_error(f"Lỗi kiểm tra đóng lệnh thông minh {symbol}: {str(e)}")
            return False

    def _find_and_add_new_coin(self):
        """Tìm và thêm coin mới vào quản lý - MỖI COIN ĐỘC LẬP - ĐÃ SỬA"""
        with self.symbol_management_lock:  # 🔴 THÊM LOCK để đảm bảo thread-safe
            try:
                # 🔴 KIỂM TRA LẠI ĐIỀU KIỆN TRONG LOCK
                if len(self.active_symbols) >= self.max_coins:
                    log_debug(f"Đã đạt giới hạn {self.max_coins} coin, không tìm coin mới")
                    return False
                    
                active_coins = self.coin_manager.get_active_coins()
                target_direction = self.get_next_side_based_on_comprehensive_analysis()
                log_info(f"Tìm coin mới - Hướng: {target_direction}, Coin đang active: {len(active_coins)}")
                
                new_symbol = self.coin_finder.find_best_coin(
                    target_direction=target_direction,
                    excluded_coins=active_coins,
                    required_leverage=self.lev
                )
                
                if new_symbol:
                    # 🔴 KIỂM TRA BỔ SUNG: Đảm bảo coin mới không có vị thế trên Binance
                    if self.coin_finder.has_existing_position(new_symbol):
                        log_warning(f"{new_symbol} - Coin mới đã có vị thế, bỏ qua")
                        return False
                        
                    success = self._add_symbol(new_symbol)
                    if success:
                        log_success(f"Đã thêm coin thứ {len(self.active_symbols)}: {new_symbol}")
                        
                        # 🔴 KIỂM TRA NGAY LẬP TỨC: Đảm bảo coin mới thêm không có vị thế
                        time.sleep(1)
                        if self.coin_finder.has_existing_position(new_symbol):
                            log_warning(f"{new_symbol} - PHÁT HIỆN CÓ VỊ THẾ SAU KHI THÊM, DỪNG THEO DÕI NGAY")
                            self.stop_symbol(new_symbol)
                            return False
                            
                        return True
                    else:
                        log_error(f"Không thể thêm symbol {new_symbol}")
                    
                return False
                
            except Exception as e:
                log_error(f"Lỗi tìm coin mới: {str(e)}", exc_info=True)
                return False

    def _add_symbol(self, symbol):
        """Thêm một symbol vào quản lý của bot - KIỂM TRA VỊ THẾ KHI THÊM - ĐÃ SỬA"""
        with self.symbol_management_lock:  # 🔴 THÊM LOCK để đảm bảo thread-safe
            if symbol in self.active_symbols:
                log_warning(f"Symbol {symbol} đã tồn tại trong bot")
                return False
                
            if len(self.active_symbols) >= self.max_coins:
                log_warning(f"Đã đạt giới hạn {self.max_coins} coin, không thể thêm {symbol}")
                return False
            
            # 🔴 KIỂM TRA QUAN TRỌNG: Đảm bảo coin không có vị thế trên Binance trước khi thêm
            if self.coin_finder.has_existing_position(symbol):
                log_warning(f"Symbol {symbol} đã có vị thế trên Binance, không thêm vào bot")
                return False
            
            # Khởi tạo dữ liệu cho symbol
            self.symbol_data[symbol] = {
                'status': 'waiting',
                'side': '',
                'qty': 0,
                'entry': 0,
                'current_price': 0,
                'position_open': False,
                'last_trade_time': 0,
                'last_close_time': 0,
                'entry_base': 0,
                'average_down_count': 0,
                'last_average_down_time': 0,
                'high_water_mark_roi': 0,
                'roi_check_activated': False,
                'close_attempted': False,
                'last_close_attempt': 0,
                'last_position_check': 0
            }
            
            self.active_symbols.append(symbol)
            self.coin_manager.register_coin(symbol)
            self.ws_manager.add_symbol(symbol, lambda price, sym=symbol: self._handle_price_update(price, sym))
            
            log_debug(f"Đã thêm symbol {symbol} vào bot, kiểm tra vị thế hiện tại")
            # Kiểm tra vị thế hiện tại
            self._check_symbol_position(symbol)
            
            # 🔴 KIỂM TRA LẦN CUỐI: Nếu phát hiện có vị thế, dừng ngay
            if self.symbol_data[symbol]['position_open']:
                log_warning(f"Symbol {symbol} có vị thế sau khi thêm, dừng theo dõi")
                self.stop_symbol(symbol)
                return False
            
            log_success(f"Đã thêm symbol {symbol} thành công")
            return True

    def _handle_price_update(self, price, symbol):
        """Xử lý cập nhật giá cho từng symbol"""
        if symbol in self.symbol_data:
            self.symbol_data[symbol]['current_price'] = price
            log_debug(f"Cập nhật giá {symbol}: {price}")

    def _check_symbol_position(self, symbol):
        """Kiểm tra vị thế cho một symbol cụ thể"""
        log_debug(f"Kiểm tra vị thế {symbol}")
        try:
            positions = get_positions(symbol, self.api_key, self.api_secret)
            if not positions:
                log_debug(f"Không có vị thế {symbol}")
                self._reset_symbol_position(symbol)
                return
            
            position_found = False
            for pos in positions:
                if pos['symbol'] == symbol:
                    position_amt = float(pos.get('positionAmt', 0))
                    if abs(position_amt) > 0:
                        position_found = True
                        self.symbol_data[symbol]['position_open'] = True
                        self.symbol_data[symbol]['status'] = "open"
                        self.symbol_data[symbol]['side'] = "BUY" if position_amt > 0 else "SELL"
                        self.symbol_data[symbol]['qty'] = position_amt
                        self.symbol_data[symbol]['entry'] = float(pos.get('entryPrice', 0))
                        
                        log_info(f"Phát hiện vị thế {symbol}: {self.symbol_data[symbol]['side']} {position_amt} @ {self.symbol_data[symbol]['entry']}")
                        
                        # Kích hoạt ROI check nếu đang có lợi nhuận
                        current_price = get_current_price(symbol)
                        if current_price > 0:
                            if self.symbol_data[symbol]['side'] == "BUY":
                                profit = (current_price - self.symbol_data[symbol]['entry']) * abs(self.symbol_data[symbol]['qty'])
                            else:
                                profit = (self.symbol_data[symbol]['entry'] - current_price) * abs(self.symbol_data[symbol]['qty'])
                                
                            invested = self.symbol_data[symbol]['entry'] * abs(self.symbol_data[symbol]['qty']) / self.lev
                            if invested > 0:
                                current_roi = (profit / invested) * 100
                                if current_roi >= self.roi_trigger:
                                    self.symbol_data[symbol]['roi_check_activated'] = True
                                    log_info(f"Kích hoạt ROI check {symbol}: ROI {current_roi:.2f}% >= {self.roi_trigger}%")
                        break
                    else:
                        position_found = True
                        log_debug(f"Vị thế {symbol} bằng 0, reset")
                        self._reset_symbol_position(symbol)
                        break
            
            if not position_found:
                log_debug(f"Không tìm thấy vị thế {symbol}")
                self._reset_symbol_position(symbol)
                
        except Exception as e:
            log_error(f"Lỗi kiểm tra vị thế {symbol}: {str(e)}")

    def _reset_symbol_position(self, symbol):
        """Reset trạng thái vị thế cho một symbol"""
        log_debug(f"Reset vị thế {symbol}")
        if symbol in self.symbol_data:
            self.symbol_data[symbol]['position_open'] = False
            self.symbol_data[symbol]['status'] = "waiting"
            self.symbol_data[symbol]['side'] = ""
            self.symbol_data[symbol]['qty'] = 0
            self.symbol_data[symbol]['entry'] = 0
            self.symbol_data[symbol]['close_attempted'] = False
            self.symbol_data[symbol]['last_close_attempt'] = 0
            self.symbol_data[symbol]['entry_base'] = 0
            self.symbol_data[symbol]['average_down_count'] = 0
            self.symbol_data[symbol]['high_water_mark_roi'] = 0
            self.symbol_data[symbol]['roi_check_activated'] = False

    def _open_symbol_position(self, symbol, side):
        """Mở vị thế cho một symbol cụ thể - KIỂM TRA VỊ THẾ TRƯỚC KHI VÀO LỆNH"""
        log_info(f"Mở vị thế {symbol} {side}")
        try:
            # 🔴 KIỂM TRA QUAN TRỌNG: Đảm bảo coin không có vị thế trên Binance trước khi vào lệnh
            if self.coin_finder.has_existing_position(symbol):
                log_warning(f"⚠️ {symbol} - ĐÃ CÓ VỊ THẾ TRÊN BINANCE, BỎ QUA VÀ TÌM COIN KHÁC")
                self.stop_symbol(symbol)
                return False

            # Kiểm tra lại trạng thái trong bot trước khi đặt lệnh
            self._check_symbol_position(symbol)
            if self.symbol_data[symbol]['position_open']:
                log_warning(f"{symbol} - Đã có vị thế trong bot, không mở lệnh mới")
                return False

            # Kiểm tra đòn bẩy
            current_leverage = self.coin_finder.get_symbol_leverage(symbol)
            if current_leverage < self.lev:
                log_error(f"❌ {symbol} - Đòn bẩy không đủ: {current_leverage}x < {self.lev}x")
                self.stop_symbol(symbol)
                return False

            if not set_leverage(symbol, self.lev, self.api_key, self.api_secret):
                log_error(f"❌ {symbol} - Không thể đặt đòn bẩy")
                self.stop_symbol(symbol)
                return False

            # Số dư
            balance = get_balance(self.api_key, self.api_secret)
            if balance is None or balance <= 0:
                log_error(f"❌ {symbol} - Không đủ số dư")
                return False

            # Giá & step size
            current_price = get_current_price(symbol)
            if current_price <= 0:
                log_error(f"❌ {symbol} - Lỗi lấy giá")
                self.stop_symbol(symbol)
                return False

            step_size = get_step_size(symbol, self.api_key, self.api_secret)
            log_debug(f"{symbol} - Step size: {step_size}")

            # Tính khối lượng
            usd_amount = balance * (self.percent / 100)
            qty = (usd_amount * self.lev) / current_price
            if step_size > 0:
                qty = math.floor(qty / step_size) * step_size
                qty = round(qty, 8)

            log_debug(f"{symbol} - Khối lượng tính toán: {qty} (số dư: {balance}, phần trăm: {self.percent}%, đòn bẩy: {self.lev}, giá: {current_price})")

            if qty <= 0 or qty < step_size:
                log_error(f"❌ {symbol} - Khối lượng không hợp lệ: {qty} < {step_size}")
                self.stop_symbol(symbol)
                return False

            log_info(f"Hủy tất cả lệnh {symbol} trước khi đặt lệnh mới")
            cancel_all_orders(symbol, self.api_key, self.api_secret)
            time.sleep(0.2)

            log_info(f"Đặt lệnh {side} {symbol} khối lượng {qty}")
            result = place_order(symbol, side, qty, self.api_key, self.api_secret)
            if result and 'orderId' in result:
                executed_qty = float(result.get('executedQty', 0))
                avg_price = float(result.get('avgPrice', current_price))

                if executed_qty >= 0:
                    # 🔴 KIỂM TRA LẦN CUỐI: Đảm bảo vị thế thực sự được mở
                    time.sleep(1)
                    self._check_symbol_position(symbol)
                    
                    if not self.symbol_data[symbol]['position_open']:
                        log_error(f"❌ {symbol} - Lệnh đã khớp nhưng không tạo được vị thế, có thể bị hủy")
                        self.stop_symbol(symbol)
                        return False
                    
                    # Cập nhật thông tin vị thế
                    self.symbol_data[symbol]['entry'] = avg_price
                    self.symbol_data[symbol]['entry_base'] = avg_price
                    self.symbol_data[symbol]['average_down_count'] = 0
                    self.symbol_data[symbol]['side'] = side
                    self.symbol_data[symbol]['qty'] = executed_qty if side == "BUY" else -executed_qty
                    self.symbol_data[symbol]['position_open'] = True
                    self.symbol_data[symbol]['status'] = "open"
                    self.symbol_data[symbol]['high_water_mark_roi'] = 0
                    self.symbol_data[symbol]['roi_check_activated'] = False

                    message = (
                        f"✅ <b>ĐÃ MỞ VỊ THẾ {symbol}</b>\n"
                        f"🤖 Bot: {self.bot_id}\n"
                        f"📌 Hướng: {side}\n"
                        f"🏷️ Giá vào: {avg_price:.4f}\n"
                        f"📊 Khối lượng: {executed_qty:.4f}\n"
                        f"💰 Đòn bẩy: {self.lev}x\n"
                        f"🎯 TP: {self.tp}% | 🛡️ SL: {self.sl}%"
                    )
                    if self.roi_trigger:
                        message += f" | 🎯 ROI Trigger: {self.roi_trigger}%"
                    
                    self.log(message)
                    log_success(f"Đã mở vị thế {symbol} {side} thành công")
                    return True
                else:
                    log_error(f"❌ {symbol} - Lệnh không khớp")
                    self.stop_symbol(symbol)
                    return False
            else:
                error_msg = result.get('msg', 'Unknown error') if result else 'No response'
                log_error(f"❌ {symbol} - Lỗi đặt lệnh: {error_msg}")
                
                # 🔴 KIỂM TRA: Nếu lỗi do đã có vị thế, dừng theo dõi coin này
                if "position" in error_msg.lower() or "exist" in error_msg.lower():
                    log_warning(f"⚠️ {symbol} - Có vấn đề với vị thế, dừng theo dõi và tìm coin khác")
                    self.stop_symbol(symbol)
                else:
                    self.stop_symbol(symbol)
                    
                return False

        except Exception as e:
            log_error(f"❌ {symbol} - Lỗi mở lệnh: {str(e)}", exc_info=True)
            self.stop_symbol(symbol)
            return False

    def _close_symbol_position(self, symbol, reason=""):
        """Đóng vị thế cho một symbol cụ thể"""
        log_info(f"Đóng vị thế {symbol}: {reason}")
        try:
            self._check_symbol_position(symbol)
            
            if not self.symbol_data[symbol]['position_open'] or abs(self.symbol_data[symbol]['qty']) <= 0:
                log_warning(f"{symbol} - Không có vị thế để đóng")
                return True

            current_time = time.time()
            if (self.symbol_data[symbol]['close_attempted'] and 
                current_time - self.symbol_data[symbol]['last_close_attempt'] < 30):
                log_debug(f"{symbol} - Đã thử đóng lệnh gần đây, chờ thêm")
                return False
            
            self.symbol_data[symbol]['close_attempted'] = True
            self.symbol_data[symbol]['last_close_attempt'] = current_time

            close_side = "SELL" if self.symbol_data[symbol]['side'] == "BUY" else "BUY"
            close_qty = abs(self.symbol_data[symbol]['qty'])
            
            log_info(f"Hủy tất cả lệnh {symbol} trước khi đóng vị thế")
            cancel_all_orders(symbol, self.api_key, self.api_secret)
            time.sleep(0.5)
            
            log_info(f"Đặt lệnh đóng {close_side} {symbol} khối lượng {close_qty}")
            result = place_order(symbol, close_side, close_qty, self.api_key, self.api_secret)
            if result and 'orderId' in result:
                current_price = get_current_price(symbol)
                pnl = 0
                if self.symbol_data[symbol]['entry'] > 0:
                    if self.symbol_data[symbol]['side'] == "BUY":
                        pnl = (current_price - self.symbol_data[symbol]['entry']) * abs(self.symbol_data[symbol]['qty'])
                    else:
                        pnl = (self.symbol_data[symbol]['entry'] - current_price) * abs(self.symbol_data[symbol]['qty'])
                
                message = (
                    f"⛔ <b>ĐÃ ĐÓNG VỊ THẾ {symbol}</b>\n"
                    f"🤖 Bot: {self.bot_id}\n"
                    f"📌 Lý do: {reason}\n"
                    f"🏷️ Giá ra: {current_price:.4f}\n"
                    f"📊 Khối lượng: {close_qty:.4f}\n"
                    f"💰 PnL: {pnl:.2f} USDC\n"
                    f"📈 Số lần nhồi: {self.symbol_data[symbol]['average_down_count']}"
                )
                self.log(message)
                
                self.symbol_data[symbol]['last_close_time'] = time.time()
                self._reset_symbol_position(symbol)
                log_success(f"Đã đóng vị thế {symbol} thành công")
                
                return True
            else:
                error_msg = result.get('msg', 'Unknown error') if result else 'No response'
                log_error(f"❌ {symbol} - Lỗi đóng lệnh: {error_msg}")
                self.symbol_data[symbol]['close_attempted'] = False
                return False
                
        except Exception as e:
            log_error(f"❌ {symbol} - Lỗi đóng lệnh: {str(e)}", exc_info=True)
            self.symbol_data[symbol]['close_attempted'] = False
            return False

    def _check_symbol_tp_sl(self, symbol):
        """Kiểm tra TP/SL cho một symbol cụ thể - ĐÃ SỬA ĐỂ TRẢ VỀ TRẠNG THÁI"""
        log_debug(f"Kiểm tra TP/SL {symbol}")
        if (not self.symbol_data[symbol]['position_open'] or 
            self.symbol_data[symbol]['entry'] <= 0 or 
            self.symbol_data[symbol]['close_attempted']):
            return False

        current_price = get_current_price(symbol)
        if current_price <= 0:
            return False

        if self.symbol_data[symbol]['side'] == "BUY":
            profit = (current_price - self.symbol_data[symbol]['entry']) * abs(self.symbol_data[symbol]['qty'])
        else:
            profit = (self.symbol_data[symbol]['entry'] - current_price) * abs(self.symbol_data[symbol]['qty'])
            
        invested = self.symbol_data[symbol]['entry'] * abs(self.symbol_data[symbol]['qty']) / self.lev
        if invested <= 0:
            return False
            
        roi = (profit / invested) * 100
        log_debug(f"{symbol} - ROI hiện tại: {roi:.2f}%")

        # CẬP NHẬT ROI CAO NHẤT
        if roi > self.symbol_data[symbol]['high_water_mark_roi']:
            self.symbol_data[symbol]['high_water_mark_roi'] = roi
            log_debug(f"{symbol} - Cập nhật ROI cao nhất: {roi:.2f}%")

        # KIỂM TRA ĐIỀU KIỆN ROI TRIGGER
        if (self.roi_trigger is not None and 
            self.symbol_data[symbol]['high_water_mark_roi'] >= self.roi_trigger and 
            not self.symbol_data[symbol]['roi_check_activated']):
            self.symbol_data[symbol]['roi_check_activated'] = True
            log_info(f"Kích hoạt ROI check {symbol}: ROI cao nhất {self.symbol_data[symbol]['high_water_mark_roi']:.2f}% >= {self.roi_trigger}%")

        # TP/SL TRUYỀN THỐNG
        position_closed = False
        if self.tp is not None and roi >= self.tp:
            log_info(f"{symbol} - Đạt TP {self.tp}% (ROI: {roi:.2f}%)")
            self._close_symbol_position(symbol, f"✅ Đạt TP {self.tp}% (ROI: {roi:.2f}%)")
            position_closed = True
        elif self.sl is not None and self.sl > 0 and roi <= -self.sl:
            log_info(f"{symbol} - Đạt SL {self.sl}% (ROI: {roi:.2f}%)")
            self._close_symbol_position(symbol, f"❌ Đạt SL {self.sl}% (ROI: {roi:.2f}%)")
            position_closed = True
            
        return position_closed

    def _check_symbol_averaging_down(self, symbol):
        """Kiểm tra nhồi lệnh cho một symbol cụ thể - ĐÃ SỬA ĐỂ TRẢ VỀ TRẠNG THÁI"""
        log_debug(f"Kiểm tra nhồi lệnh {symbol}")
        if (not self.symbol_data[symbol]['position_open'] or 
            not self.symbol_data[symbol]['entry_base'] or 
            self.symbol_data[symbol]['average_down_count'] >= 7):
            return False
            
        try:
            current_time = time.time()
            if current_time - self.symbol_data[symbol]['last_average_down_time'] < 60:
                return False
                
            current_price = get_current_price(symbol)
            if current_price <= 0:
                return False
                
            # Tính ROI ÂM hiện tại (lỗ)
            if self.symbol_data[symbol]['side'] == "BUY":
                profit = (current_price - self.symbol_data[symbol]['entry_base']) * abs(self.symbol_data[symbol]['qty'])
            else:
                profit = (self.symbol_data[symbol]['entry_base'] - current_price) * abs(self.symbol_data[symbol]['qty'])
                
            invested = self.symbol_data[symbol]['entry_base'] * abs(self.symbol_data[symbol]['qty']) / self.lev
            if invested <= 0:
                return False
                
            current_roi = (profit / invested) * 100
            
            # Chỉ xét khi ROI ÂM (đang lỗ)
            if current_roi >= 0:
                return False
                
            # Chuyển ROI âm thành số dương để so sánh
            roi_negative = abs(current_roi)
            log_debug(f"{symbol} - ROI âm: {roi_negative:.2f}%")
            
            # Các mốc Fibonacci
            fib_levels = [200, 300, 500, 800, 1300, 2100, 3400]
            
            if self.symbol_data[symbol]['average_down_count'] < len(fib_levels):
                current_fib_level = fib_levels[self.symbol_data[symbol]['average_down_count']]
                
                if roi_negative >= current_fib_level:
                    log_info(f"{symbol} - Đạt mốc nhồi lệnh Fibonacci {current_fib_level}% (ROI âm: {roi_negative:.2f}%)")
                    if self._execute_symbol_average_down(symbol):
                        self.symbol_data[symbol]['last_average_down_time'] = current_time
                        self.symbol_data[symbol]['average_down_count'] += 1
                        log_success(f"Đã nhồi lệnh Fibonacci {symbol} ở mốc {current_fib_level}% lỗ")
                        return True
                        
            return False
            
        except Exception as e:
            log_error(f"Lỗi kiểm tra nhồi lệnh {symbol}: {str(e)}")
            return False

    def _execute_symbol_average_down(self, symbol):
        """Thực hiện nhồi lệnh cho một symbol cụ thể"""
        log_info(f"Thực hiện nhồi lệnh {symbol}")
        try:
            balance = get_balance(self.api_key, self.api_secret)
            if balance is None or balance <= 0:
                log_error("Không đủ số dư để nhồi lệnh")
                return False
                
            current_price = get_current_price(symbol)
            if current_price <= 0:
                return False
                
            # Khối lượng nhồi = % số dư * (số lần nhồi + 1)
            additional_percent = self.percent * (self.symbol_data[symbol]['average_down_count'] + 1)
            usd_amount = balance * (additional_percent / 100)
            qty = (usd_amount * self.lev) / current_price
            
            step_size = get_step_size(symbol, self.api_key, self.api_secret)
            if step_size > 0:
                qty = math.floor(qty / step_size) * step_size
                qty = round(qty, 8)
            
            if qty < step_size:
                log_error(f"Khối lượng nhồi quá nhỏ: {qty} < {step_size}")
                return False
                
            log_info(f"Đặt lệnh nhồi {self.symbol_data[symbol]['side']} {symbol} khối lượng {qty}")
            # Đặt lệnh cùng hướng với vị thế hiện tại
            result = place_order(symbol, self.symbol_data[symbol]['side'], qty, self.api_key, self.api_secret)
            
            if result and 'orderId' in result:
                executed_qty = float(result.get('executedQty', 0))
                avg_price = float(result.get('avgPrice', current_price))
                
                if executed_qty >= 0:
                    # Cập nhật giá trung bình và khối lượng
                    total_qty = abs(self.symbol_data[symbol]['qty']) + executed_qty
                    new_entry = (abs(self.symbol_data[symbol]['qty']) * self.symbol_data[symbol]['entry'] + executed_qty * avg_price) / total_qty
                    self.symbol_data[symbol]['entry'] = new_entry
                    self.symbol_data[symbol]['qty'] = total_qty if self.symbol_data[symbol]['side'] == "BUY" else -total_qty
                    
                    message = (
                        f"📈 <b>ĐÃ NHỒI LỆNH {symbol}</b>\n"
                        f"🔢 Lần nhồi: {self.symbol_data[symbol]['average_down_count'] + 1}\n"
                        f"📊 Khối lượng thêm: {executed_qty:.4f}\n"
                        f"🏷️ Giá nhồi: {avg_price:.4f}\n"
                        f"📈 Giá trung bình mới: {new_entry:.4f}\n"
                        f"💰 Tổng khối lượng: {total_qty:.4f}"
                    )
                    self.log(message)
                    log_success(f"Đã nhồi lệnh {symbol} thành công")
                    return True
                    
            return False
            
        except Exception as e:
            log_error(f"Lỗi nhồi lệnh {symbol}: {str(e)}", exc_info=True)
            return False

    def stop_symbol(self, symbol):
        """Dừng một symbol cụ thể (đóng vị thế và ngừng theo dõi) - ĐÃ SỬA ĐỂ TÌM COIN MỚI"""
        with self.symbol_management_lock:  # 🔴 THÊM LOCK để đảm bảo thread-safe
            if symbol not in self.active_symbols:
                log_warning(f"Symbol {symbol} không tồn tại trong bot")
                return False
            
            log_info(f"Đang dừng coin {symbol}...")
            
            # Nếu đang xử lý coin này, đợi nó xong
            if self.current_processing_symbol == symbol:
                log_info(f"Đang xử lý {symbol}, chờ hoàn tất...")
                timeout = time.time() + 10
                while self.current_processing_symbol == symbol and time.time() < timeout:
                    time.sleep(0.5)
            
            # Đóng vị thế nếu đang mở
            if self.symbol_data[symbol]['position_open']:
                log_info(f"Đóng vị thế {symbol} đang mở")
                self._close_symbol_position(symbol, "Dừng coin theo lệnh")
            
            # Dọn dẹp
            self.ws_manager.remove_symbol(symbol)
            self.coin_manager.unregister_coin(symbol)
            
            if symbol in self.symbol_data:
                del self.symbol_data[symbol]
            
            if symbol in self.active_symbols:
                self.active_symbols.remove(symbol)
            
            log_success(f"Đã dừng coin {symbol} | Còn lại: {len(self.active_symbols)}/{self.max_coins} coin")
            
            # 🔴 QUAN TRỌNG: TÌM COIN MỚI NGAY SAU KHI DỪNG COIN
            if len(self.active_symbols) < self.max_coins:
                log_info(f"Tự động tìm coin mới thay thế cho {symbol}...")
                # Gọi hàm tìm coin mới ngay lập tức
                threading.Thread(target=self._delayed_find_new_coin, daemon=True).start()
            
            return True

    def _delayed_find_new_coin(self):
        """Tìm coin mới với độ trễ nhỏ để tránh xung đột"""
        log_debug("Tìm coin mới sau khi dừng coin (delayed)")
        time.sleep(2)  # Chờ 2 giây để đảm bảo việc dừng coin hoàn tất
        self._find_and_add_new_coin()

    def stop_all_symbols(self):
        """Dừng tất cả coin nhưng vẫn giữ bot chạy"""
        log_info("Đang dừng tất cả coin...")
        
        symbols_to_stop = self.active_symbols.copy()
        stopped_count = 0
        
        for symbol in symbols_to_stop:
            if self.stop_symbol(symbol):
                stopped_count += 1
                time.sleep(1)
        
        log_success(f"Đã dừng {stopped_count} coin, bot vẫn chạy và có thể thêm coin mới")
        return stopped_count

    def stop(self):
        """Dừng toàn bộ bot (đóng tất cả vị thế)"""
        log_info(f"Dừng bot {self.bot_id}")
        self._stop = True
        stopped_count = self.stop_all_symbols()
        log_success(f"Bot dừng - Đã dừng {stopped_count} coin")

    def check_global_positions(self):
        """Kiểm tra vị thế toàn tài khoản"""
        log_debug("Kiểm tra vị thế toàn tài khoản")
        try:
            positions = get_positions(api_key=self.api_key, api_secret=self.api_secret)
            if not positions:
                self.global_long_count = 0
                self.global_short_count = 0
                self.global_long_pnl = 0
                self.global_short_pnl = 0
                log_debug("Không có vị thế nào trên toàn tài khoản")
                return
            
            long_count = 0
            short_count = 0
            long_pnl_total = 0
            short_pnl_total = 0
            
            for pos in positions:
                position_amt = float(pos.get('positionAmt', 0))
                unrealized_pnl = float(pos.get('unRealizedProfit', 0))
                
                if position_amt > 0:
                    long_count += 1
                    long_pnl_total += unrealized_pnl
                elif position_amt < 0:
                    short_count += 1
                    short_pnl_total += unrealized_pnl
            
            self.global_long_count = long_count
            self.global_short_count = short_count
            self.global_long_pnl = long_pnl_total
            self.global_short_pnl = short_pnl_total
            
            log_debug(f"Vị thế toàn tài khoản - LONG: {long_count} (PnL: {long_pnl_total:.2f}), SHORT: {short_count} (PnL: {short_pnl_total:.2f})")
            
        except Exception as e:
            if time.time() - self.last_error_log_time > 30:
                log_error(f"Lỗi kiểm tra vị thế toàn tài khoản: {str(e)}")
                self.last_error_log_time = time.time()

    def get_next_side_based_on_comprehensive_analysis(self):
        """Xác định hướng lệnh tiếp theo dựa trên PHÂN TÍCH PnL TOÀN TÀI KHOẢN"""
        log_debug("Xác định hướng lệnh tiếp theo")
        self.check_global_positions()
        
        long_pnl = self.global_long_pnl
        short_pnl = self.global_short_pnl
        
        log_debug(f"Phân tích PnL - LONG: {long_pnl:.2f}, SHORT: {short_pnl:.2f}")
        
        if long_pnl > short_pnl:
            log_debug("LONG PnL > SHORT PnL -> Chọn BUY")
            return "BUY"
        elif short_pnl > long_pnl:
            log_debug("SHORT PnL > LONG PnL -> Chọn SELL")
            return "SELL"
        else:
            side = random.choice(["BUY", "SELL"])
            log_debug(f"PnL bằng nhau -> Chọn ngẫu nhiên: {side}")
            return side

    def log(self, message):
        """Ghi log và gửi Telegram cho các thông tin quan trọng"""
        # Chỉ log các message có chứa emoji hoặc từ khóa quan trọng
        important_keywords = ['❌', '✅', '⛔', '💰', '📈', '📊', '🎯', '🛡️', '🔴', '🟢', '⚠️', '🚫']
        if any(keyword in message for keyword in important_keywords):
            log_warning(f"[{self.bot_id}] {message}")
            if self.telegram_bot_token and self.telegram_chat_id:
                send_telegram(f"<b>{self.bot_id}</b>: {message}", 
                             chat_id=self.telegram_chat_id,
                             bot_token=self.telegram_bot_token, 
                             default_chat_id=self.telegram_chat_id)

# ========== BOT GLOBAL MARKET VỚI HỆ THỐNG RSI + KHỐI LƯỢNG ==========
class GlobalMarketBot(BaseBot):
    def __init__(self, symbol, lev, percent, tp, sl, roi_trigger, ws_manager,
                 api_key, api_secret, telegram_bot_token, telegram_chat_id, bot_id=None, **kwargs):
        log_info(f"Khởi tạo GlobalMarketBot: {bot_id}")
        super().__init__(symbol, lev, percent, tp, sl, roi_trigger, ws_manager,
                         api_key, api_secret, telegram_bot_token, telegram_chat_id,
                         "Hệ-thống-RSI-Khối-lượng", bot_id=bot_id, **kwargs)

# ========== KHỞI TẠO GLOBAL INSTANCES ==========
coin_manager = CoinManager()
log_info("Khởi tạo global instances hoàn tất")

# Kết thúc Part 1
log_info("======= KẾT THÚC PHẦN 1 =======")
