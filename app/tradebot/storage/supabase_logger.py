from __future__ import annotations

import logging
from datetime import datetime

from app.tradebot.models.schema import SignalState

logger = logging.getLogger(__name__)


class SupabaseLogger:
    def __init__(self, url: str | None, key: str | None) -> None:
        self._enabled = bool(url and key)
        self._client = None
        if self._enabled:
            try:
                from supabase import create_client
                self._client = create_client(url, key)
            except Exception as exc:
                logger.warning('Supabase init failed: %s', exc)
                self._enabled = False

    def is_enabled(self) -> bool:
        return self._enabled and self._client is not None

    def log_signal(self, signal: SignalState, sent_at: datetime, bot_source: str = 'tradebot') -> None:
        if not self.is_enabled():
            return
        try:
            self._client.table('signals').insert({
                'symbol': signal.symbol,
                'action': signal.action,
                'confidence': signal.confidence,
                'buy_score': signal.buy_score,
                'sell_score': signal.sell_score,
                'price': signal.price,
                'support': signal.support,
                'resistance': signal.resistance,
                'invalidation': signal.invalidation,
                'sent_at': sent_at.isoformat(),
                'as_of': signal.as_of.isoformat(),
                'bot_source': bot_source,
            }).execute()
        except Exception as exc:
            logger.warning('Supabase log_signal failed for %s: %s', signal.symbol, exc)
