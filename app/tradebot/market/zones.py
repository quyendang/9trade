from __future__ import annotations

import pandas as pd

from app.tradebot.models.schema import ChartIndicators, ChartZone


ZONE_LOOKBACK = 60
ZONE_RANGE_PCT = 0.20


def build_chart_candles(frame: pd.DataFrame) -> list[dict]:
    candles: list[dict] = []
    for row in frame.itertuples(index=False):
        candles.append(
            {
                'time': int(row.open_time.timestamp()),
                'open': float(row.open),
                'high': float(row.high),
                'low': float(row.low),
                'close': float(row.close),
            }
        )
    return candles


def build_hybrid_zones(frame: pd.DataFrame) -> tuple[list[ChartZone], ChartIndicators]:
    if frame.empty:
        raise ValueError('Cannot build chart zones from empty frame')

    latest = frame.iloc[-1]
    window = frame.tail(min(ZONE_LOOKBACK, len(frame)))
    recent_high = float(window['high'].max())
    recent_low = float(window['low'].min())
    price_range = recent_high - recent_low
    if price_range <= 0:
        raise ValueError('Cannot build chart zones from a flat price range')

    buy_low = recent_low
    buy_high = recent_low + (price_range * ZONE_RANGE_PCT)
    sell_low = recent_high - (price_range * ZONE_RANGE_PCT)
    sell_high = recent_high

    close = float(latest['close'])
    atr = float(latest['atr_14'])
    rsi = float(latest['rsi_14'])
    macd_hist = float(latest['macd_histogram'])
    ema_50 = float(latest['ema_50'])
    bb_lower = float(latest['bollinger_lower'])
    bb_upper = float(latest['bollinger_upper'])
    support = float(latest['swing_low'])
    resistance = float(latest['swing_high'])

    indicators = ChartIndicators(
        support=support,
        resistance=resistance,
        ema_50=ema_50,
        bollinger_lower=bb_lower,
        bollinger_upper=bb_upper,
        atr_14=atr,
        rsi_14=rsi,
        macd_histogram=macd_hist,
    )

    zones = [
        ChartZone(
            low=float(min(buy_low, buy_high)),
            high=float(max(buy_low, buy_high)),
            zone_type='buy',
            status=_zone_status(close, buy_low, buy_high, atr),
            note=(
                f'Dynamic buy zone from the latest {len(window)} { _plural_candle(len(window)) } range; '
                f'watch RSI {rsi:.1f}, EMA50 {ema_50:.2f}, lower band {bb_lower:.2f}.'
            ),
        ),
        ChartZone(
            low=float(min(sell_low, sell_high)),
            high=float(max(sell_low, sell_high)),
            zone_type='sell',
            status=_zone_status(close, sell_low, sell_high, atr),
            note=(
                f'Dynamic sell zone from the latest {len(window)} { _plural_candle(len(window)) } range; '
                f'watch RSI {rsi:.1f}, EMA50 {ema_50:.2f}, upper band {bb_upper:.2f}.'
            ),
        ),
    ]
    return zones, indicators


def _zone_status(price: float, low: float, high: float, atr: float) -> str:
    zone_low = min(low, high)
    zone_high = max(low, high)
    if zone_low <= price <= zone_high:
        return 'active'
    distance = min(abs(price - zone_low), abs(price - zone_high))
    if atr > 0 and distance <= atr:
        return 'near'
    return 'neutral'


def _plural_candle(count: int) -> str:
    return 'candle' if count == 1 else 'candles'
