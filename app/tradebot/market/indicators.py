from __future__ import annotations

import pandas as pd
import ta

from app.tradebot.models.schema import IndicatorSnapshot


REQUIRED_COLUMNS = {'open', 'high', 'low', 'close', 'volume', 'open_time', 'close_time'}


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f'Missing OHLCV columns: {sorted(missing)}')

    df = frame.copy()
    df['ema_50'] = ta.trend.ema_indicator(df['close'], window=50)
    df['ema_200'] = ta.trend.ema_indicator(df['close'], window=200)
    df['rsi_14'] = ta.momentum.rsi(df['close'], window=14)

    macd = ta.trend.MACD(df['close'], window_slow=26, window_fast=12, window_sign=9)
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['macd_histogram'] = macd.macd_diff()

    bands = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
    df['bollinger_upper'] = bands.bollinger_hband()
    df['bollinger_middle'] = bands.bollinger_mavg()
    df['bollinger_lower'] = bands.bollinger_lband()

    df['atr_14'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], window=14)
    df['swing_high'] = df['high'].rolling(window=20, min_periods=1).max()
    df['swing_low'] = df['low'].rolling(window=20, min_periods=1).min()

    # Volume features (Agent 2 - Volume Specialist):
    # vol_ratio = volume / SMA20(volume); dùng để confirm breakout/breakdown.
    df['volume_sma_20'] = df['volume'].rolling(window=20, min_periods=1).mean()
    df['volume_ratio'] = df['volume'] / df['volume_sma_20'].replace(0, float('nan'))
    return df


def latest_snapshot(symbol: str, timeframe: str, frame: pd.DataFrame) -> IndicatorSnapshot:
    latest = frame.iloc[-1]
    required = [
        'ema_50',
        'ema_200',
        'rsi_14',
        'macd',
        'macd_signal',
        'macd_histogram',
        'bollinger_upper',
        'bollinger_middle',
        'bollinger_lower',
        'atr_14',
        'swing_high',
        'swing_low',
    ]
    if latest[required].isna().any():
        raise ValueError(f'Indicator calculation incomplete for {symbol} {timeframe}; increase kline_limit')

    return IndicatorSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        open_time=latest['open_time'].to_pydatetime(),
        close_time=latest['close_time'].to_pydatetime(),
        open=float(latest['open']),
        high=float(latest['high']),
        low=float(latest['low']),
        close=float(latest['close']),
        volume=float(latest['volume']),
        ema_50=float(latest['ema_50']),
        ema_200=float(latest['ema_200']),
        rsi_14=float(latest['rsi_14']),
        macd=float(latest['macd']),
        macd_signal=float(latest['macd_signal']),
        macd_histogram=float(latest['macd_histogram']),
        bollinger_upper=float(latest['bollinger_upper']),
        bollinger_middle=float(latest['bollinger_middle']),
        bollinger_lower=float(latest['bollinger_lower']),
        atr_14=float(latest['atr_14']),
        swing_high=float(latest['swing_high']),
        swing_low=float(latest['swing_low']),
    )
