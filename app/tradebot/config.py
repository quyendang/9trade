from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'tradebot'
    environment: str = 'development'
    log_level: str = 'INFO'
    host: str = '0.0.0.0'
    port: int = 8000

    check_interval_seconds: int = Field(default=600, ge=1)
    request_timeout_seconds: int = 20

    exchange_base_url: str = 'https://api.binance.com'
    exchange_provider: str = 'binance'
    default_symbols: list[str] = Field(default_factory=lambda: ['BTCUSDT', 'ETHUSDT'])
    default_timeframes: list[str] = Field(default_factory=lambda: ['1h', '4h', '1d'])
    kline_limit: int = 300

    openai_api_key: str | None = None
    openai_model: str = 'gpt-4.1-mini'
    openai_base_url: str | None = None
    portkey_api_key: str | None = None
    ai_chart_timeframe: str = '4h'
    ai_chart_candle_limit: int = Field(default=140, ge=60, le=400)

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_cooldown_minutes: int = 60
    telegram_score_delta: int = 8
    telegram_min_buy_score: int = 72
    telegram_min_sell_score: int = 72

    state_path: Path = Path('/app/data/state.json')

    supabase_url: str | None = None
    supabase_key: str | None = None


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    configure_logging(settings.log_level)
    return settings
