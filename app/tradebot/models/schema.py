from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = 'ok'


class IndicatorSnapshot(BaseModel):
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    ema_50: float
    ema_200: float
    rsi_14: float
    macd: float
    macd_signal: float
    macd_histogram: float
    bollinger_upper: float
    bollinger_middle: float
    bollinger_lower: float
    atr_14: float
    swing_high: float
    swing_low: float


class SymbolIndicatorResponse(BaseModel):
    symbol: str
    timeframes: dict[str, IndicatorSnapshot] = Field(default_factory=dict)


class IndicatorTestResponse(BaseModel):
    provider: str
    symbols: dict[str, SymbolIndicatorResponse] = Field(default_factory=dict)


class OpenAIAnalysis(BaseModel):
    summary: str = 'AI analysis unavailable'
    risk_notes: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    telegram_note: str = 'AI analysis unavailable'
    data_quality_warning: bool = False


class PriceZone(BaseModel):
    low: float
    high: float
    zone_type: Literal['pullback_buy', 'breakout_buy', 'rejection_sell', 'breakdown_sell']
    note: str


class TimeframeScore(BaseModel):
    timeframe: str
    buy_score: int
    sell_score: int
    support: float
    resistance: float
    invalidation: float
    reasons: list[str] = Field(default_factory=list)
    indicators: IndicatorSnapshot


class SignalState(BaseModel):
    symbol: str
    action: Literal['BUY', 'SELL', 'BUY_WATCH', 'SELL_WATCH', 'WAIT_CONFLICT', 'HOLD']
    confidence: Literal['high', 'medium', 'low']
    buy_score: int
    sell_score: int
    price: float
    support: float
    resistance: float
    invalidation: float
    as_of: datetime
    reasons: list[str] = Field(default_factory=list)
    timeframe_scores: list[TimeframeScore] = Field(default_factory=list)
    ai_analysis: OpenAIAnalysis = Field(default_factory=OpenAIAnalysis)
    buy_zone: PriceZone | None = None
    sell_zone: PriceZone | None = None


class TelegramState(BaseModel):
    last_action: str | None = None
    last_score: int | None = None
    last_sent_at: datetime | None = None
    last_message: str | None = None


class SignalEnvelope(BaseModel):
    signals: dict[str, SignalState] = Field(default_factory=dict)
    updated_at: datetime | None = None


class PersistedState(BaseModel):
    signals: dict[str, SignalState] = Field(default_factory=dict)
    telegram: dict[str, TelegramState] = Field(default_factory=dict)
    updated_at: datetime | None = None


class RunOnceResponse(BaseModel):
    status: str
    updated_symbols: list[str] = Field(default_factory=list)
    detail: str
