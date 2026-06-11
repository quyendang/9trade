from __future__ import annotations

import logging

import httpx

from app.tradebot.config import Settings
from app.tradebot.models.schema import ChartIndicators, ChartZone

logger = logging.getLogger(__name__)


class PushoverNotifier:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_enabled(self) -> bool:
        return bool(
            self._settings.pushover_enabled
            and self._settings.pushover_token
            and self._settings.pushover_user
        )

    def build_zone_message(
        self,
        symbol: str,
        timeframe: str,
        price: float,
        zone: ChartZone,
        indicators: ChartIndicators,
    ) -> tuple[str, str]:
        side = 'BUY' if zone.zone_type == 'buy' else 'SELL'
        title = f'Tradebot {side} zone | {symbol} {timeframe}'
        message = (
            f'{symbol} entered {side} zone on {timeframe}\n'
            f'Price: {price:.2f}\n'
            f'Zone: {zone.low:.2f} - {zone.high:.2f}\n'
            f'Status: {zone.status}\n'
            f'RSI: {indicators.rsi_14:.1f}\n'
            f'MACD hist: {indicators.macd_histogram:.4f}\n'
            f'Support: {indicators.support:.2f}\n'
            f'Resistance: {indicators.resistance:.2f}'
        )
        return title, message

    async def send_zone_alert(
        self,
        symbol: str,
        timeframe: str,
        price: float,
        zone: ChartZone,
        indicators: ChartIndicators,
    ) -> str | None:
        if not self.is_enabled():
            logger.info('Pushover not configured, skipping zone alert for %s %s', symbol, timeframe)
            return None

        title, message = self.build_zone_message(symbol, timeframe, price, zone, indicators)
        payload = {
            'token': self._settings.pushover_token,
            'user': self._settings.pushover_user,
            'title': title,
            'message': message,
            'priority': 0,
            'sound': self._settings.pushover_sound,
        }
        if self._settings.pushover_device:
            payload['device'] = self._settings.pushover_device

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self._settings.request_timeout_seconds)) as client:
                response = await client.post('https://api.pushover.net/1/messages.json', data=payload)
                response.raise_for_status()
            return message
        except Exception as exc:  # noqa: BLE001
            logger.warning('Pushover zone alert failed for %s %s: %s', symbol, timeframe, exc)
            return None
