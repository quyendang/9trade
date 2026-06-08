from __future__ import annotations

from datetime import UTC, datetime

from app.tradebot.config import Settings
from app.tradebot.models.schema import SignalState, TelegramState


class AntiSpamPolicy:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def should_send(self, signal: SignalState, previous: TelegramState | None) -> bool:
        if signal.action == 'HOLD':
            return False

        dominant_score = max(signal.buy_score, signal.sell_score)
        is_strong = (
            signal.buy_score >= self._settings.telegram_min_buy_score
            or signal.sell_score >= self._settings.telegram_min_sell_score
        )
        if previous is None or previous.last_action is None:
            return is_strong

        if signal.action != previous.last_action:
            return True

        if previous.last_score is not None and abs(dominant_score - previous.last_score) >= self._settings.telegram_score_delta:
            return True

        if not is_strong or previous.last_sent_at is None:
            return False

        elapsed = (datetime.now(UTC) - previous.last_sent_at).total_seconds()
        return elapsed >= self._settings.telegram_cooldown_minutes * 60
