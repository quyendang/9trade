from __future__ import annotations

from abc import ABC, abstractmethod

import httpx
import pandas as pd

from app.tradebot.config import Settings


class ExchangeProvider(ABC):
    @abstractmethod
    async def fetch_klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    async def fetch_order_book(self, symbol: str, limit: int) -> dict:
        raise NotImplementedError


class BinancePublicExchange(ExchangeProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def fetch_klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        url = f'{self._settings.exchange_base_url}/api/v3/klines'
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        timeout = httpx.Timeout(self._settings.request_timeout_seconds)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()

        if not payload:
            raise ValueError(f'No kline data returned for {symbol} {interval}')

        frame = pd.DataFrame(
            payload,
            columns=[
                'open_time',
                'open',
                'high',
                'low',
                'close',
                'volume',
                'close_time',
                'quote_asset_volume',
                'number_of_trades',
                'taker_buy_base_asset_volume',
                'taker_buy_quote_asset_volume',
                'ignore',
            ],
        )

        for column in ['open', 'high', 'low', 'close', 'volume']:
            frame[column] = pd.to_numeric(frame[column], errors='coerce')

        frame['open_time'] = pd.to_datetime(frame['open_time'], unit='ms', utc=True)
        frame['close_time'] = pd.to_datetime(frame['close_time'], unit='ms', utc=True)
        frame = frame.dropna(subset=['open', 'high', 'low', 'close', 'volume']).reset_index(drop=True)
        return frame

    async def fetch_order_book(self, symbol: str, limit: int) -> dict:
        url = f'{self._settings.exchange_base_url}/api/v3/depth'
        params = {'symbol': symbol, 'limit': limit}
        timeout = httpx.Timeout(self._settings.request_timeout_seconds)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()

        if not payload or 'bids' not in payload or 'asks' not in payload:
            raise ValueError(f'No order book data returned for {symbol}')
        return payload


def get_exchange_provider(settings: Settings) -> ExchangeProvider:
    provider = settings.exchange_provider.lower()
    if provider == 'binance':
        return BinancePublicExchange(settings)
    raise ValueError(f'Unsupported exchange provider: {settings.exchange_provider}')
