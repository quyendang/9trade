import logging
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.ethbot.tracker import (
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    RSI_PERIOD,
    TRACKER_INTERVAL,
    _bollinger_bands,
    _compute_ema_series,
    _compute_eth_zones_from_range,
    _compute_macd_series,
    _compute_rsi_series,
    _rsi_fetch_klines,
    _stochastic_oscillator,
    _williams_r,
    rsi_status_payload,
    run_symbol_tracker_once,
)

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="app/ethbot/templates")

# Router gốc của ethbot (dashboard + health), sẽ được mount với prefix /ethbot
router = APIRouter(tags=["ethbot"])
# Router con /bots giữ nguyên các endpoint JSON gốc của ethbot
bots_router = APIRouter(prefix="/bots", tags=["ethbot-bots"])


@bots_router.get("/rsi-status")
def rsi_status():
    return rsi_status_payload()


@bots_router.get("/run/{symbol}")
def run_tracker(symbol: str):
    return run_symbol_tracker_once(symbol, send_notify=False)


def _render_symbol_dashboard(request: Request, symbol: str):
    symbol = symbol.upper()

    try:
        klines = _rsi_fetch_klines(symbol, TRACKER_INTERVAL, limit=200)
    except Exception as e:
        logger.error("[SYMBOL DASH] Error fetching klines for %s: %s", symbol, e)
        klines = []

    labels: List[str] = []
    closes: List[float] = []
    highs: List[float] = []
    lows: List[float] = []

    for k in klines:
        try:
            dt = datetime.utcfromtimestamp(int(k[0]) / 1000.0)
            labels.append(dt.strftime("%Y-%m-%d %H:%M"))
            highs.append(float(k[2]))
            lows.append(float(k[3]))
            closes.append(float(k[4]))
        except Exception:
            continue

    if not closes:
        return templates.TemplateResponse(
            request,
            "symbol_dashboard.html",
            {
                "request": request,
                "symbol": symbol,
                "rows_json": [],
                "last_price": None,
                "last_rsi": None,
                "change_24h": None,
                "buy_low": None,
                "buy_high": None,
                "sell_low": None,
                "sell_high": None,
                "tracker_action": "HOLD",
                "tracker_reason": "No data",
            },
        )

    rsi_values = _compute_rsi_series(closes, RSI_PERIOD)
    _, _, macd_hist_values = _compute_macd_series(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    ema_fast = _compute_ema_series(closes, 12)
    ema_slow = _compute_ema_series(closes, 26)
    _, bb_upper, bb_lower = _bollinger_bands(closes, period=20, k=2.0)
    stoch_k = _stochastic_oscillator(highs, lows, closes, period=14)
    williams_r = _williams_r(highs, lows, closes, period=14)

    buy_low = buy_high = sell_low = sell_high = None
    try:
        sell_low, sell_high, buy_low, buy_high, _, _ = _compute_eth_zones_from_range(symbol, TRACKER_INTERVAL, lookback=60)
    except Exception as e:
        logger.error("[SYMBOL DASH] Error computing zones for %s: %s", symbol, e)

    min_len = min(
        len(closes),
        len(labels),
        len(rsi_values),
        len(macd_hist_values),
        len(ema_fast),
        len(ema_slow),
        len(bb_upper),
        len(bb_lower),
        len(stoch_k),
        len(williams_r),
    )

    labels = labels[-min_len:]
    closes = closes[-min_len:]
    rsi_values = rsi_values[-min_len:]
    macd_hist_values = macd_hist_values[-min_len:]
    ema_fast = ema_fast[-min_len:]
    ema_slow = ema_slow[-min_len:]
    bb_upper = bb_upper[-min_len:]
    bb_lower = bb_lower[-min_len:]
    stoch_k = stoch_k[-min_len:]
    williams_r = williams_r[-min_len:]

    rows_json: List[Dict[str, Any]] = []
    for i in range(min_len):
        rows_json.append(
            {
                "time_str": labels[i],
                "price": closes[i],
                "rsi_h4": rsi_values[i],
                "macd_hist": macd_hist_values[i],
                "ema_fast": ema_fast[i],
                "ema_slow": ema_slow[i],
                "bb_upper": bb_upper[i],
                "bb_lower": bb_lower[i],
                "stoch_k": stoch_k[i],
                "wr": williams_r[i],
            }
        )

    last_price = closes[-1]
    last_rsi = rsi_values[-1] if rsi_values else None
    change_24h = None
    if len(closes) >= 7 and closes[-7] != 0:
        change_24h = (last_price - closes[-7]) / closes[-7] * 100.0

    tracker_action = "HOLD"
    tracker_reason = ""
    try:
        payload = run_symbol_tracker_once(symbol, send_notify=False)
        tracker_action = payload.get("action", "HOLD")
        tracker_reason = payload.get("reason", "")
    except Exception as e:
        logger.error("[SYMBOL DASH] run_symbol_tracker_once failed for %s: %s", symbol, e)

    return templates.TemplateResponse(
        request,
        "symbol_dashboard.html",
        {
            "request": request,
            "symbol": symbol,
            "rows_json": rows_json,
            "last_price": last_price,
            "last_rsi": last_rsi,
            "change_24h": change_24h,
            "buy_low": buy_low,
            "buy_high": buy_high,
            "sell_low": sell_low,
            "sell_high": sell_high,
            "tracker_action": tracker_action,
            "tracker_reason": tracker_reason,
        },
    )


@router.get("/")
def home_redirect():
    return RedirectResponse(url="/ethbot/ETHUSDT", status_code=307)


@router.get("/health")
def health():
    return {
        "ok": True,
        "service": "qapi-crypto",
        "time_utc": datetime.utcnow().isoformat() + "Z",
    }


# Dùng `def` (không async) để FastAPI dispatch vào threadpool — tránh chặn event loop
# vì _render_symbol_dashboard gọi requests.get đồng bộ.
@router.get("/ETHUSDT", response_class=HTMLResponse)
def ethusdt_dashboard(request: Request):
    return _render_symbol_dashboard(request, "ETHUSDT")


@router.get("/BTCUSDT", response_class=HTMLResponse)
def btcusdt_dashboard(request: Request):
    return _render_symbol_dashboard(request, "BTCUSDT")
