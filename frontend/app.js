// app.js

// Nếu backend deploy riêng domain: đổi API_BASE = "https://your-api.com"
const API_BASE = "";

// Token & user toàn cục
let authToken = null;
let currentUsername = null;

// Chart & WebSocket
let priceChart = null;
let priceData = [];
let labelData = [];
let ws = null;
let currentSymbol = "BTCUSDT"; // 👈 coin đang vẽ biểu đồ

// ================= API helper =================
async function apiRequest(path, { method = "GET", body = null, auth = true } = {}) {
    const url = API_BASE + path;
    const headers = { "Content-Type": "application/json" };
    if (auth && authToken) headers["X-Auth-Token"] = authToken;

    const res = await fetch(url, {
        method,
        headers,
        body: body ? JSON.stringify(body) : null,
    });
    if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || `HTTP ${res.status}`);
    }
    return res.json();
}

// ================= DOM utils =================
function $(selector) {
    return document.querySelector(selector);
}

function renderBaseLayout(innerHTML) {
    const app = document.getElementById("app");
    app.innerHTML = `
        <div class="app">
          <div class="topbar">
            <div class="topbar-left">
              <div class="logo-circle">Q</div>
              <div>
                <div class="topbar-title">QUAN TERMINAL</div>
                <div class="topbar-sub">Paper trading / demo Binance futures</div>
              </div>
            </div>
            <div class="topbar-right">
              <div class="user-chip">
                <div class="user-avatar">${(currentUsername || "U")[0].toUpperCase()}</div>
                <div>
                  <div>${currentUsername || "Guest"}</div>
                  <div style="font-size:11px;color:#9ca3af;">Binance Futures (real, cẩn thận rủi ro)</div>

                </div>
              </div>
            </div>
          </div>

          <div class="shell">
            <aside class="sidebar">
              <div>
                <div class="sidebar-section-title">Main</div>
                <button class="sidebar-btn" data-screen="dashboard">📊 Dashboard</button>
                <button class="sidebar-btn" data-screen="config">⚙️ Cấu hình bot</button>
                <button class="sidebar-btn" data-screen="apikey">🔑 API Binance</button>
              </div>
              <div>
                <button class="sidebar-btn danger" id="btn-logout">Đăng xuất</button>
              </div>
            </aside>
            <main class="content">
              ${innerHTML}
            </main>
          </div>
        </div>
    `;
}

// =============== Auth screen ===============
function renderAuthScreen(message = "") {
    const app = document.getElementById("app");
    app.innerHTML = `
      <div class="topbar">
        <div class="topbar-left">
          <div class="logo-circle">Q</div>
          <div>
            <div class="topbar-title">QUAN TERMINAL</div>
            <div class="topbar-sub">Đăng nhập để điều khiển bot</div>
          </div>
        </div>
      </div>
      <div class="auth-wrapper">
        <div class="auth-card">
          <h2>Đăng nhập</h2>
          <p>Tài khoản lưu trong DB, dùng lại được ở server khác.</p>
          ${message ? `<div class="status err">${message}</div>` : ""}
          <form id="auth-form">
            <div class="form-group">
              <label>Username</label>
              <input type="text" name="username" required />
            </div>
            <div class="form-group">
              <label>Password</label>
              <input type="password" name="password" required />
            </div>
            <div class="btn-row">
              <button class="btn btn-primary" type="submit" data-action="login">Đăng nhập</button>
              <button class="btn btn-secondary" type="button" id="btn-register">Đăng ký & đăng nhập</button>
            </div>
          </form>
        </div>
      </div>
    `;

    const form = document.getElementById("auth-form");
    const btnRegister = document.getElementById("btn-register");

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(form);
        const username = fd.get("username").trim();
        const password = fd.get("password");

        if (!username || !password) {
            renderAuthScreen("Không được để trống username/password.");
            return;
        }

        try {
            const data = await apiRequest("/api/login", {
                method: "POST",
                body: { username, password },
                auth: false,
            });
            authToken = data.token;
            currentUsername = data.username;
            localStorage.setItem("authToken", authToken);
            localStorage.setItem("username", currentUsername);
            await afterLogin();
        } catch (err) {
            renderAuthScreen("Lỗi đăng nhập: " + err.message);
        }
    });

    btnRegister.addEventListener("click", async () => {
        const fd = new FormData(form);
        const username = fd.get("username").trim();
        const password = fd.get("password");
        if (!username || !password) {
            renderAuthScreen("Không được để trống username/password.");
            return;
        }

        try {
            const data = await apiRequest("/api/register", {
                method: "POST",
                body: { username, password },
                auth: false,
            });
            authToken = data.token;
            currentUsername = data.username;
            localStorage.setItem("authToken", authToken);
            localStorage.setItem("username", currentUsername);
            await afterLogin();
        } catch (err) {
            renderAuthScreen("Lỗi đăng ký: " + err.message);
        }
    });
}

// =============== Setup API key ===============
function renderSetupAccount(message = "") {
    renderBaseLayout(`
      <div class="setup-wrapper">
        <div class="setup-card">
          <h2>Cấu hình API Binance</h2>
          <p>Nhập API Key & Secret. Cấu hình lưu trong DB theo user.</p>
          ${message ? `<div class="status err">${message}</div>` : ""}
          <form id="api-form">
            <div class="form-group">
              <label>Binance API Key</label>
              <input type="text" name="api_key" required />
            </div>
            <div class="form-group">
              <label>Binance Secret</label>
              <input type="text" name="api_secret" required />
            </div>
            <div class="btn-row">
              <button class="btn btn-primary" type="submit">Lưu cấu hình</button>
              <button class="btn btn-secondary" type="button" data-screen="dashboard">Bỏ qua</button>
            </div>
          </form>
        </div>
      </div>
    `);

    document.querySelectorAll("[data-screen]").forEach((btn) => {
        btn.addEventListener("click", () => changeScreen(btn.dataset.screen));
    });

    const form = document.getElementById("api-form");
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(form);
        const api_key = fd.get("api_key").trim();
        const api_secret = fd.get("api_secret").trim();
        try {
            await apiRequest("/api/setup-account", {
                method: "POST",
                body: { api_key, api_secret },
            });
            changeScreen("dashboard");
        } catch (err) {
            renderSetupAccount("Lỗi lưu API key: " + err.message);
        }
    });
}


// =============== Bot Config ===============
function renderConfigScreen(message = "") {
    renderBaseLayout(`
      <div class="config-wrapper">
        <div class="config-card">
          <h2>Cấu hình bot giao dịch</h2>
          ${message ? `<div class="status err">${message}</div>` : ""}
          <form id="config-form">
            <div class="form-group">
              <label>Chế độ bot</label>
              <select name="bot_mode">
                <option value="static">Static (1 symbol cố định)</option>
                <option value="dynamic">Dynamic (quét nhiều symbol)</option>
              </select>
            </div>
            <div class="form-group">
              <label>Symbol (VD: BTCUSDT)</label>
              <input type="text" name="symbol" placeholder="BTCUSDT" />
            </div>
            <div class="form-group">
              <label>Đòn bẩy</label>
              <input type="number" name="lev" value="20" />
            </div>
            <div class="form-group">
              <label>% vốn mỗi lệnh</label>
              <input type="number" name="percent" value="5" step="0.1" />
            </div>
            <div class="form-group">
              <label>TP (%)</label>
              <input type="number" name="tp" value="10" step="0.1" />
            </div>
            <div class="form-group">
              <label>SL (%)</label>
              <input type="number" name="sl" value="20" step="0.1" />
            </div>
            <div class="form-group">
              <label>ROI trigger (%) (optional)</label>
              <input type="number" name="roi_trigger" step="0.1" />
            </div>
            <div class="form-group">
              <label>Số lượng bot chạy song song</label>
              <input type="number" name="bot_count" value="1" />
            </div>
            <div class="btn-row">
              <button class="btn btn-primary" type="submit">Lưu cấu hình</button>
              <button class="btn btn-secondary" type="button" data-screen="dashboard">Về Dashboard</button>
            </div>
          </form>
        </div>
      </div>
    `);

    document.querySelectorAll("[data-screen]").forEach((btn) => {
        btn.addEventListener("click", () => changeScreen(btn.dataset.screen));
    });

    // Load config hiện tại
    (async () => {
        try {
            const cfg = await apiRequest("/api/bot-config");
            if (!cfg) return;
            const form = document.getElementById("config-form");
            form.bot_mode.value = cfg.bot_mode;
            if (cfg.symbol) form.symbol.value = cfg.symbol;
            form.lev.value = cfg.lev;
            form.percent.value = cfg.percent;
            form.tp.value = cfg.tp;
            form.sl.value = cfg.sl;
            if (cfg.roi_trigger != null) form.roi_trigger.value = cfg.roi_trigger;
            form.bot_count.value = cfg.bot_count;
        } catch (err) {
            console.error("Load config error", err);
        }
    })();

    const form = document.getElementById("config-form");
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(form);
        const payload = {
            bot_mode: fd.get("bot_mode"),
            symbol: fd.get("symbol") || null,
            lev: Number(fd.get("lev")),
            percent: Number(fd.get("percent")),
            tp: Number(fd.get("tp")),
            sl: Number(fd.get("sl")),
            roi_trigger: fd.get("roi_trigger") ? Number(fd.get("roi_trigger")) : null,
            bot_count: Number(fd.get("bot_count")),
        };
        try {
            await apiRequest("/api/bot-config", {
                method: "POST",
                body: payload,
            });
            renderConfigScreen("Đã lưu cấu hình.");
        } catch (err) {
            renderConfigScreen("Lỗi lưu cấu hình: " + err.message);
        }
    });
}

// =============== Dashboard ===============
function renderDashboard() {
    renderBaseLayout(`
      <div class="dashboard">
        <section class="panel">
          <div class="panel-header">
            <div>
              <h2>Giá Futures realtime</h2>
              <p>Giá Futures lấy từ Binance, chọn coin bên phải và cập nhật qua WebSocket.</p>
            </div>
            <div class="panel-actions">
              <input
                id="symbol-input"
                class="input"
                placeholder="BTCUSDT"
                value="BTCUSDT"
                style="width:120px;margin-right:8px;"
              />
              <button class="btn btn-secondary" id="btn-apply-symbol">Đổi coin</button>
              <button class="btn btn-secondary" id="btn-bot-start">Start bot</button>
              <button class="btn btn-secondary" id="btn-bot-stop">Stop bot</button>
            </div>
          </div>
          <div class="chart-wrapper">
            <canvas id="price-chart"></canvas>
          </div>
          <div class="panel-footer">
            <div id="bot-status-text" class="status"></div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-header">
            <h2>Số dư Futures</h2>
            <p>Số dư tài khoản Futures (availableBalance) cập nhật realtime qua WebSocket.</p>
          </div>
          <div class="panel-body">
            <div id="pnl-balance" class="pnl-balance">Loading...</div>
          </div>
        </section>

      </div>
    `);

    document.getElementById("btn-bot-start").addEventListener("click", async () => {
        try {
            await apiRequest("/api/bot-start", { method: "POST" });
            loadBotStatus();
        } catch (err) {
            alert("Lỗi start bot: " + err.message);
        }
    });
    
    document.getElementById("btn-bot-stop").addEventListener("click", async () => {
        try {
            await apiRequest("/api/bot-stop", { method: "POST" });
            loadBotStatus();
        } catch (err) {
            alert("Lỗi stop bot: " + err.message);
        }
    });
    
    // 👇 THÊM MỚI
    const symbolInput = document.getElementById("symbol-input");
    const btnApplySymbol = document.getElementById("btn-apply-symbol");
    if (symbolInput) {
        symbolInput.value = currentSymbol || "BTCUSDT";
    }
    if (btnApplySymbol && symbolInput) {
        btnApplySymbol.addEventListener("click", () => {
            const sym = symbolInput.value.trim().toUpperCase();
            if (!sym) return;
            currentSymbol = sym;
    
            // reset dữ liệu chart khi đổi coin
            priceData = [];
            labelData = [];
            if (priceChart) {
                priceChart.data.labels = labelData;
                priceChart.data.datasets[0].data = priceData;
                priceChart.update();
            }
    
            connectPriceWS(currentSymbol);
        });
    }
    // 👆 HẾT PHẦN THÊM
    
    setupSidebarEvents();
    initChart();
    connectPriceWS(currentSymbol);  // 👈 truyền currentSymbol
    connectPnlWS();
    loadBotStatus();
}

function setupSidebarEvents() {
    document.querySelectorAll(".sidebar-btn[data-screen]").forEach((btn) => {
        btn.addEventListener("click", () => changeScreen(btn.dataset.screen));
    });

    const btnLogout = document.getElementById("btn-logout");
    if (btnLogout) {
        btnLogout.addEventListener("click", () => {
            authToken = null;
            currentUsername = null;
            localStorage.removeItem("authToken");
            localStorage.removeItem("username");
            if (ws) {
                ws.close();
                ws = null;
            }
            renderAuthScreen("Đã đăng xuất.");
        });
    }
}

async function loadBotStatus() {
    try {
        const st = await apiRequest("/api/bot-status");
        const el = document.getElementById("bot-status-text");
        if (!el) return;

        if (st.running) {
            const botCount = st.bot_count ?? 0;
            const syms = (st.active_symbols && st.active_symbols.length)
                ? st.active_symbols.join(", ")
                : (st.symbol || "auto");

            el.textContent =
                `Bot đang chạy | bots: ${botCount} | symbols: ${syms} | mode: ${st.mode}`;
            el.className = "status ok";
        } else {
            el.textContent = `Bot đang tắt. (mode: ${st.mode}, symbol: ${st.symbol || "auto"})`;
            el.className = "status";
        }
    } catch (err) {
        console.error("Load bot status error", err);
    }
}

// =============== Chart ===============
function initChart() {
    const ctx = document.getElementById("price-chart");
    if (!ctx) return;

    priceData = [];
    labelData = [];

    priceChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: labelData,
            datasets: [
                {
                    label: "Price",
                    data: priceData,
                    borderWidth: 2,
                    tension: 0.2,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
              legend: { display: false },
              title: { display: true, text: currentSymbol + " price" },
            },

            scales: {
                x: {
                    ticks: { color: "#9ca3af", maxTicksLimit: 6 },
                    grid: { display: false },
                },
                y: {
                    ticks: { color: "#9ca3af", maxTicksLimit: 5 },
                    grid: { color: "rgba(31,41,55,0.7)" },
                },
            },
        },
    });
}

// =============== WebSocket ===============
function connectPriceWS(symbol) {
    // cập nhật symbol hiện tại (nếu người dùng nhập)
    if (symbol) {
        currentSymbol = symbol.toUpperCase();
    }
    if (!currentSymbol) {
        currentSymbol = "BTCUSDT";
    }

    if (ws) {
        ws.close();
        ws = null;
    }

    const url = (location.protocol === "https:" ? "wss://" : "ws://") +
        location.host +
        `/ws/price?token=${encodeURIComponent(authToken)}&symbol=${encodeURIComponent(currentSymbol)}`;

    ws = new WebSocket(url);
    ws.onopen = () => {
        console.log("WS price connected for", currentSymbol);
    };
    ws.onmessage = (ev) => {
        try {
            const data = JSON.parse(ev.data);
            if (data.error) {
                console.error("WS price error:", data);
                return;
            }

            if (priceData.length > 50) {
                priceData.shift();
                labelData.shift();
            }

            priceData.push(data.price);
            const t = new Date(data.timestamp * 1000);
            labelData.push(
              `${t.getHours()}:${String(t.getMinutes()).padStart(2, "0")}:${String(t.getSeconds()).padStart(2, "0")}`
            );

            if (priceChart) {
                if (
                  priceChart.options &&
                  priceChart.options.plugins &&
                  priceChart.options.plugins.title
                ) {
                    priceChart.options.plugins.title.text = currentSymbol + " price";
                }
                priceChart.update("none");
            }
        } catch (e) {
            console.error("WS parse error", e);
        }
    };
    ws.onclose = () => {
        console.log("WS price closed");
    };
}


function connectPnlWS() {
    const url = (location.protocol === "https:" ? "wss://" : "ws://") +
        location.host +
        `/ws/pnl?token=${encodeURIComponent(authToken)}`;
    const sock = new WebSocket(url);
    sock.onmessage = (ev) => {
        try {
            const data = JSON.parse(ev.data);
            const el = document.getElementById("pnl-balance");
            if (el) {
                if (data.error) {
                    el.textContent = `Lỗi: ${data.error}`;
                } else if (typeof data.balance === "number") {
                    el.textContent = `Balance: ${data.balance.toFixed(2)} USDT`;
                } else {
                    el.textContent = "Đang chờ dữ liệu số dư...";
                }
            }
        } catch (e) {
            console.error("WS pnl parse error", e);
        }
    };
}


// =============== Screen routing ===============
async function changeScreen(screen) {
    if (screen === "dashboard") {
        renderDashboard();
    } else if (screen === "config") {
        renderConfigScreen();
    } else if (screen === "apikey") {
        renderSetupAccount();
    }
}

// =============== After login ===============
async function afterLogin() {
    try {
        const status = await apiRequest("/api/account-status");
        if (status.configured) {
            await renderDashboard();
        } else {
            renderSetupAccount();
        }
    } catch (err) {
        console.error("afterLogin error", err);
        renderAuthScreen("Phiên đăng nhập hết hạn, vui lòng đăng nhập lại.");
        authToken = null;
        currentUsername = null;
        localStorage.removeItem("authToken");
        localStorage.removeItem("username");
    }
}

// =============== INIT ===============
function init() {
    authToken = localStorage.getItem("authToken");
    currentUsername = localStorage.getItem("username");
    if (authToken && currentUsername) afterLogin();
    else renderAuthScreen();
}

init();
