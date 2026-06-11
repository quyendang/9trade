from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.tradebot.models.schema import PersistedState, PushoverZoneState, SignalState, TelegramState


class StateStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> PersistedState:
        if not self._path.exists():
            return PersistedState()
        return PersistedState.model_validate_json(self._path.read_text(encoding='utf-8'))

    def save(self, state: PersistedState) -> PersistedState:
        state.updated_at = datetime.now(UTC)
        self._path.write_text(state.model_dump_json(indent=2), encoding='utf-8')
        return state

    def save_signals(self, signals: dict[str, SignalState]) -> PersistedState:
        state = self.load()
        state.signals = signals
        return self.save(state)

    def update_telegram_state(self, symbol: str, signal: SignalState, message: str) -> PersistedState:
        state = self.load()
        state.telegram[symbol] = TelegramState(
            last_action=signal.action,
            last_score=max(signal.buy_score, signal.sell_score),
            last_sent_at=datetime.now(UTC),
            last_message=message,
        )
        state.signals[symbol] = signal
        return self.save(state)

    def update_pushover_zone_state(
        self,
        key: str,
        zone_type: str | None,
        status: str | None,
        message: str | None = None,
        sent: bool = False,
    ) -> PersistedState:
        state = self.load()
        previous = state.pushover_zones.get(key, PushoverZoneState())
        state.pushover_zones[key] = PushoverZoneState(
            last_zone_type=zone_type,
            last_status=status,
            last_sent_at=datetime.now(UTC) if sent else previous.last_sent_at,
            last_seen_at=datetime.now(UTC),
            last_message=message if sent else previous.last_message,
        )
        return self.save(state)
