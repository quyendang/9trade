import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

from app.ethbot.supabase_logger import EthbotSupabaseLogger

logger = logging.getLogger(__name__)

# ENV
PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN", "")
PUSHOVER_USER = os.getenv("PUSHOVER_USER", "")
PUSHOVER_DEVICE = os.getenv("PUSHOVER_DEVICE", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

_supabase = EthbotSupabaseLogger(SUPABASE_URL or None, SUPABASE_KEY or None)

TRACKED_SYMBOLS = ["ETHUSDT", "BTCUSDT"]
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
TRACKER_INTERVAL = os.getenv("TRACKER_INTERVAL", "4h")

ETH_RSI_SELL = float(os.getenv("ETH_RSI_SELL", "65"))
ETH_RSI_BUY = float(os.getenv("ETH_RSI_BUY", "40"))
MACD_FAST = int(os.getenv("ETH_MACD_FAST", "12"))
MACD_SLOW = int(os.getenv("ETH_MACD_SLOW", "26"))
MACD_SIGNAL = int(os.getenv("ETH_MACD_SIGNAL", "9"))
TRACKER_CHECK_MINUTES = int(os.getenv("TRACKER_CHECK_MINUTES", "10"))

_rsi_last_values: Dict[str, Dict[str, Dict[str, float]]] = {}
_rsi_last_state: Dict[str, Dict[str, str]] = {sym: {TRACKER_INTERVAL: "unknown"} for sym in TRACKED_SYMBOLS}
_rsi_last_run: float = 0.0


def _rsi_fetch_klines(symbol: str, interval: str, limit: int = 200):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _rsi_wilder(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        raise ValueError("Not enough data to compute RSI")

    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def _rsi_latest(symbol: str, interval: str, period: int):
    kl = _rsi_fetch_klines(symbol, interval, limit=max(200, period * 5))
    closes = [float(k[4]) for k in kl]
    return closes[-1], _rsi_wilder(closes, period=period)


def _compute_ema_series(values: List[float], period: int) -> List[Optional[float]]:
    if len(values) < period:
        raise ValueError(f"Not enough data for EMA({period})")
    ema_values: List[Optional[float]] = [None] * len(values)
    sma = sum(values[:period]) / period
    ema_values[period - 1] = sma
    k = 2 / (period + 1)
    ema_prev = sma
    for i in range(period, len(values)):
        ema = (values[i] - ema_prev) * k + ema_prev
        ema_values[i] = ema
        ema_prev = ema
    return ema_values


def _compute_macd_series(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    if len(closes) < slow + signal + 5:
        n = len(closes)
        return [0.0] * n, [0.0] * n, [0.0] * n

    ema_fast = _compute_ema_series(closes, fast)
    ema_slow = _compute_ema_series(closes, slow)

    macd_series: List[float] = []
    for ef, es in zip(ema_fast, ema_slow):
        macd_series.append(0.0 if ef is None or es is None else ef - es)

    signal_series = _compute_ema_series(macd_series, signal)
    hist_series: List[float] = []
    for m, s in zip(macd_series, signal_series):
        hist_series.append(0.0 if s is None else m - s)

    return macd_series, signal_series, hist_series


def _macd_latest_with_prev(symbol: str, interval: str):
    kl = _rsi_fetch_klines(symbol, interval, limit=max(200, MACD_SLOW * 5))
    closes = [float(k[4]) for k in kl]
    macd, signal, _ = _compute_macd_series(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    if len(macd) < 2 or len(signal) < 2:
        raise ValueError("Not enough data to compute MACD latest")
    hist = macd[-1] - (signal[-1] or 0.0)
    prev_hist = macd[-2] - (signal[-2] or 0.0)
    return macd[-1], (signal[-1] or 0.0), hist, prev_hist


def _compute_eth_zones_from_range(symbol: str, interval: str, lookback: int = 60):
    kl = _rsi_fetch_klines(symbol, interval, limit=lookback)
    highs = [float(k[2]) for k in kl]
    lows = [float(k[3]) for k in kl]
    recent_high = max(highs)
    recent_low = min(lows)
    price_range = recent_high - recent_low
    if price_range <= 0:
        raise ValueError("Invalid price range")

    zone_pct = 0.2
    buy_low = recent_low
    buy_high = recent_low + zone_pct * price_range
    sell_high = recent_high
    sell_low = recent_high - zone_pct * price_range
    return sell_low, sell_high, buy_low, buy_high, recent_low, recent_high


def _compute_rsi_series(closes: List[float], period: int) -> List[float]:
    if len(closes) < period + 2:
        return [50.0] * len(closes)

    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    def ema(series, p):
        alpha = 2 / (p + 1)
        vals = []
        prev = sum(series[:p]) / p
        vals.append(prev)
        for v in series[p:]:
            prev = alpha * v + (1 - alpha) * prev
            vals.append(prev)
        return vals

    avg_gain = ema(gains, period)
    avg_loss = ema(losses, period)
    rsi = [50.0] * len(closes)
    offset = len(closes) - len(avg_gain)

    for i in range(len(avg_gain)):
        if avg_loss[i] == 0:
            rsi[offset + i] = 100.0
        else:
            rs = avg_gain[i] / avg_loss[i]
            rsi[offset + i] = 100 - (100 / (1 + rs))

    return rsi


def _sma_series(values: List[float], period: int):
    n = len(values)
    if n < period:
        return [None] * n
    out = [None] * (period - 1)
    wsum = sum(values[:period])
    out.append(wsum / period)
    for i in range(period, n):
        wsum += values[i] - values[i - period]
        out.append(wsum / period)
    return out


def _bollinger_bands(values: List[float], period: int = 20, k: float = 2.0):
    import math

    n = len(values)
    middle = _sma_series(values, period)
    upper = [None] * n
    lower = [None] * n

    if n < period:
        return middle, upper, lower

    for i in range(period - 1, n):
        window = values[i - period + 1 : i + 1]
        m = middle[i]
        if m is None:
            continue
        std = math.sqrt(sum((v - m) ** 2 for v in window) / period)
        upper[i] = m + k * std
        lower[i] = m - k * std

    return middle, upper, lower


def _stochastic_oscillator(highs: List[float], lows: List[float], closes: List[float], period: int = 14):
    n = len(closes)
    if n < period:
        return [None] * n

    out = [None] * n
    for i in range(period - 1, n):
        h = max(highs[i - period + 1 : i + 1])
        l = min(lows[i - period + 1 : i + 1])
        out[i] = 50.0 if h == l else (closes[i] - l) / (h - l) * 100.0
    return out


def _williams_r(highs: List[float], lows: List[float], closes: List[float], period: int = 14):
    n = len(closes)
    if n < period:
        return [None] * n

    out = [None] * n
    for i in range(period - 1, n):
        h = max(highs[i - period + 1 : i + 1])
        l = min(lows[i - period + 1 : i + 1])
        out[i] = -50.0 if h == l else -100.0 * (h - closes[i]) / (h - l)
    return out


def _pushover_notify(title: str, message: str):
    if not PUSHOVER_TOKEN or not PUSHOVER_USER:
        return
    data = {
        "token": PUSHOVER_TOKEN,
        "user": PUSHOVER_USER,
        "title": title,
        "message": message,
        "priority": 0,
        "sound": "cash",
    }
    if PUSHOVER_DEVICE:
        data["device"] = PUSHOVER_DEVICE

    try:
        requests.post("https://api.pushover.net/1/messages.json", data=data, timeout=15)
    except Exception:
        pass


def _eth_decide_action(
    price: float,
    rsi_h4: float,
    macd_hist: float,
    prev_macd_hist: float,
    zones: tuple,
    btc_rsi_h4: float,
    btc_macd_hist: float,
    btc_prev_macd_hist: float,
):
    sell_low, sell_high, buy_low, buy_high, recent_low, recent_high = zones
    reasons: List[str] = [
        f"Dynamic zones: BUY[{buy_low:.1f}-{buy_high:.1f}] SELL[{sell_low:.1f}-{sell_high:.1f}] (range {recent_low:.1f}-{recent_high:.1f})"
    ]
    action = "HOLD"

    macd_weakening = macd_hist > 0 and prev_macd_hist is not None and macd_hist < prev_macd_hist
    if sell_low <= price <= sell_high and rsi_h4 >= ETH_RSI_SELL and macd_weakening:
        action = "SELL"
        reasons.append(f"Price {price:.1f} in SELL zone & RSI_H4 {rsi_h4:.1f} >= {ETH_RSI_SELL}")
    elif buy_low <= price <= buy_high and rsi_h4 <= ETH_RSI_BUY:
        action = "BUY"
        reasons.append(f"Price {price:.1f} in BUY zone & RSI_H4 {rsi_h4:.1f} <= {ETH_RSI_BUY}")
    else:
        reasons.append("No buy/sell condition matched (HOLD).")

    btc_bull_rsi = btc_rsi_h4 >= 65
    btc_macd_stronger = btc_macd_hist > 0 and btc_prev_macd_hist is not None and btc_macd_hist >= btc_prev_macd_hist
    if action == "SELL" and (btc_bull_rsi or btc_macd_stronger):
        action = "HOLD"
        reasons.append(
            f"Cancel SELL: BTC still bullish (RSI_H4={btc_rsi_h4:.1f}, MACD hist {btc_macd_hist:.4f} >= prev {btc_prev_macd_hist:.4f})"
        )

    return {"action": action, "reason": " | ".join(reasons)}


def run_symbol_tracker_once(symbol: str, send_notify: bool = False):
    symbol = symbol.upper()

    price, rsi_h4 = _rsi_latest(symbol, TRACKER_INTERVAL, RSI_PERIOD)
    macd_line, macd_signal, macd_hist, prev_macd_hist = _macd_latest_with_prev(symbol, TRACKER_INTERVAL)

    btc_price, btc_rsi_h4 = _rsi_latest("BTCUSDT", TRACKER_INTERVAL, RSI_PERIOD)
    _, _, btc_macd_hist, btc_prev_macd_hist = _macd_latest_with_prev("BTCUSDT", TRACKER_INTERVAL)

    zones = _compute_eth_zones_from_range(symbol, TRACKER_INTERVAL, lookback=60)
    sell_low, sell_high, buy_low, buy_high, recent_low, recent_high = zones

    decision = _eth_decide_action(
        price, rsi_h4, macd_hist, prev_macd_hist, zones, btc_rsi_h4, btc_macd_hist, btc_prev_macd_hist
    )

    payload = {
        "symbol": symbol,
        "timeframe": TRACKER_INTERVAL,
        "now_utc": datetime.utcnow().isoformat() + "Z",
        "price": price,
        "rsi_h4": rsi_h4,
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "action": decision["action"],
        "reason": decision["reason"],
        "zones": {
            "sell_low": sell_low,
            "sell_high": sell_high,
            "buy_low": buy_low,
            "buy_high": buy_high,
            "recent_low": recent_low,
            "recent_high": recent_high,
        },
        "btc": {
            "price": btc_price,
            "rsi_h4": btc_rsi_h4,
            "macd_hist": btc_macd_hist,
            "prev_macd_hist": btc_prev_macd_hist,
        },
    }

    if send_notify and payload["action"] != "HOLD":
        _pushover_notify(
            f"[{payload['action']}] {symbol}",
            f"Price: {price}\nReason: {payload['reason']}\nTime (UTC): {payload['now_utc']}",
        )
        sell_low, sell_high, buy_low, buy_high, _, _ = zones
        support = buy_low if payload["action"] == "BUY" else sell_low
        resistance = sell_high if payload["action"] == "SELL" else buy_high
        _supabase.log_signal(
            symbol=symbol,
            action=payload["action"],
            price=price,
            support=support,
            resistance=resistance,
            reason=payload["reason"],
            as_of=datetime.now(timezone.utc),
        )

    return payload


def symbols_tracker_job():
    for symbol in TRACKED_SYMBOLS:
        try:
            payload = run_symbol_tracker_once(symbol, send_notify=True)
            logger.info("[SYMBOL_TRACKER_JOB] %s: action=%s price=%s", symbol, payload["action"], payload["price"])
        except Exception as e:
            logger.error("[SYMBOL_TRACKER_JOB] %s: %s", symbol, e)


def rsi_check_once():
    global _rsi_last_run, _rsi_last_values

    snap: Dict[str, Dict[str, Dict[str, float]]] = {TRACKER_INTERVAL: {}}
    for sym in TRACKED_SYMBOLS:
        try:
            price, rsi = _rsi_latest(sym, TRACKER_INTERVAL, RSI_PERIOD)
            snap[TRACKER_INTERVAL][sym] = {"price": price, "rsi": rsi}
        except Exception as e:
            snap[TRACKER_INTERVAL][sym] = {"error": str(e)}

    _rsi_last_values = snap
    _rsi_last_run = datetime.utcnow().timestamp()


def rsi_status_payload():
    return {
        "symbols": TRACKED_SYMBOLS,
        "period": RSI_PERIOD,
        "timeframes": {TRACKER_INTERVAL: TRACKER_INTERVAL},
        "last_run_utc": datetime.utcfromtimestamp(_rsi_last_run).strftime("%Y-%m-%d %H:%M:%S") if _rsi_last_run else None,
        "values": _rsi_last_values,
        "state": _rsi_last_state,
        "check_every_minutes": TRACKER_CHECK_MINUTES,
    }
