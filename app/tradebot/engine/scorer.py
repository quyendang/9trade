from __future__ import annotations

import pandas as pd

from app.tradebot.market.indicators import latest_snapshot
from app.tradebot.models.schema import TimeframeScore


class TechnicalScorer:
    def score_timeframe(self, symbol: str, timeframe: str, frame: pd.DataFrame) -> TimeframeScore:
        snapshot = latest_snapshot(symbol, timeframe, frame)
        latest = frame.iloc[-1]
        previous = frame.iloc[-2] if len(frame) > 1 else frame.iloc[-1]

        buy_score = 0
        sell_score = 0
        reasons: list[str] = []

        close = snapshot.close
        ema_50 = snapshot.ema_50
        ema_200 = snapshot.ema_200
        rsi = snapshot.rsi_14
        macd = snapshot.macd
        macd_signal = snapshot.macd_signal
        macd_hist = snapshot.macd_histogram
        prev_macd_hist = float(previous['macd_histogram'])
        bb_upper = snapshot.bollinger_upper
        bb_middle = snapshot.bollinger_middle
        bb_lower = snapshot.bollinger_lower
        atr = snapshot.atr_14
        support = snapshot.swing_low
        resistance = snapshot.swing_high

        if close > ema_50:
            buy_score += 10
            reasons.append(f'{timeframe}: close above EMA50')
        else:
            sell_score += 10
            reasons.append(f'{timeframe}: close below EMA50')

        if close > ema_200:
            buy_score += 14
            reasons.append(f'{timeframe}: close above EMA200')
        else:
            sell_score += 14
            reasons.append(f'{timeframe}: close below EMA200')

        if ema_50 > ema_200:
            buy_score += 12
            reasons.append(f'{timeframe}: EMA50 above EMA200')
        else:
            sell_score += 12
            reasons.append(f'{timeframe}: EMA50 below EMA200')

        if rsi >= 55:
            buy_score += 10
            reasons.append(f'{timeframe}: RSI bullish at {rsi:.1f}')
        elif rsi <= 45:
            sell_score += 10
            reasons.append(f'{timeframe}: RSI bearish at {rsi:.1f}')
        else:
            reasons.append(f'{timeframe}: RSI neutral at {rsi:.1f}')

        if rsi <= 30:
            buy_score += 8
            reasons.append(f'{timeframe}: oversold rebound setup')
        elif rsi >= 70:
            sell_score += 8
            reasons.append(f'{timeframe}: overbought pullback risk')

        if macd > macd_signal:
            buy_score += 14
            reasons.append(f'{timeframe}: MACD above signal')
        else:
            sell_score += 14
            reasons.append(f'{timeframe}: MACD below signal')

        if macd_hist > prev_macd_hist:
            buy_score += 8
            reasons.append(f'{timeframe}: MACD histogram improving')
        else:
            sell_score += 8
            reasons.append(f'{timeframe}: MACD histogram weakening')

        if close > bb_middle:
            buy_score += 6
            reasons.append(f'{timeframe}: above Bollinger midline')
        else:
            sell_score += 6
            reasons.append(f'{timeframe}: below Bollinger midline')

        if close <= bb_lower:
            buy_score += 6
            reasons.append(f'{timeframe}: near lower band support')
        elif close >= bb_upper:
            sell_score += 6
            reasons.append(f'{timeframe}: near upper band resistance')

        if close >= resistance * 0.995:
            buy_score += 12
            reasons.append(f'{timeframe}: testing recent swing high')
        if close <= support * 1.005:
            sell_score += 12
            reasons.append(f'{timeframe}: testing recent swing low')

        # ---- Volume confirmation cho breakout/breakdown (Agent 2: Volume Specialist) ----
        # Verify trên 6 năm: weak-volume breakout có win-rate thấp đáng kể.
        # Mục tiêu: tránh bull-trap / bear-trap khi giá chạm support/resistance
        # mà thiếu volume xác nhận.
        vol_ratio = float(latest['volume_ratio']) if 'volume_ratio' in frame.columns else None
        if vol_ratio is not None and not pd.isna(vol_ratio):
            near_resistance = close >= resistance * 0.995
            near_support = close <= support * 1.005
            if near_resistance:
                if vol_ratio >= 1.5:
                    buy_score += 4
                    reasons.append(f'{timeframe}: breakout volume confirmation (x{vol_ratio:.2f})')
                elif vol_ratio < 0.7:
                    buy_score = max(0, buy_score - 6)
                    reasons.append(f'{timeframe}: weak-volume breakout warning (x{vol_ratio:.2f})')
            if near_support:
                if vol_ratio >= 1.5:
                    sell_score += 4
                    reasons.append(f'{timeframe}: breakdown volume confirmation (x{vol_ratio:.2f})')
                elif vol_ratio < 0.7:
                    sell_score = max(0, sell_score - 6)
                    reasons.append(f'{timeframe}: weak-volume breakdown warning (x{vol_ratio:.2f})')

        if atr / close >= 0.03:
            buy_score = max(0, buy_score - 4)
            sell_score = max(0, sell_score - 4)
            reasons.append(f'{timeframe}: ATR volatility penalty')

        invalidation = support - atr if buy_score >= sell_score else resistance + atr
        return TimeframeScore(
            timeframe=timeframe,
            buy_score=min(buy_score, 100),
            sell_score=min(sell_score, 100),
            support=support,
            resistance=resistance,
            invalidation=invalidation,
            reasons=reasons,
            indicators=snapshot,
        )
