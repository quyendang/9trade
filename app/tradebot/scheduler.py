from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.tradebot.ai.openai_analyzer import OpenAIAnalyzer
from app.tradebot.config import Settings
from app.tradebot.engine.evaluator import SignalEvaluator
from app.tradebot.market.charting import ChartRenderer
from app.tradebot.market.exchange import ExchangeProvider
from app.tradebot.market.indicators import add_indicators
from app.tradebot.market.zones import build_hybrid_zones
from app.tradebot.models.schema import ChartZone, PushoverZoneState, SignalEnvelope, SignalState
from app.tradebot.notify.anti_spam import AntiSpamPolicy
from app.tradebot.notify.pushover import PushoverNotifier
from app.tradebot.notify.telegram import TelegramNotifier
from app.tradebot.storage.state import StateStore
from app.tradebot.storage.supabase_logger import SupabaseLogger

logger = logging.getLogger(__name__)


class SignalService:
    def __init__(self, settings: Settings, exchange: ExchangeProvider, state_store: StateStore) -> None:
        self._settings = settings
        self._exchange = exchange
        self._state_store = state_store
        self._anti_spam = AntiSpamPolicy(settings)
        self._notifier = TelegramNotifier(settings)
        self._pushover = PushoverNotifier(settings)
        self._evaluator = SignalEvaluator()
        self._supabase = SupabaseLogger(settings.supabase_url, settings.supabase_key)
        self._ai_analyzer = OpenAIAnalyzer(
            settings.openai_api_key,
            settings.openai_model,
            settings.openai_base_url,
            settings.portkey_api_key,
            settings.request_timeout_seconds,
        )
        self._chart_renderer = ChartRenderer(
            timeframe=settings.ai_chart_timeframe,
            candle_limit=settings.ai_chart_candle_limit,
        )

    async def run_once(self, allow_notifications: bool = True) -> list[str]:
        state = self._state_store.load()
        signals = state.signals
        updated: list[str] = []

        for symbol in self._settings.default_symbols:
            timeframe_frames = {}
            for timeframe in self._settings.default_timeframes:
                frame = await self._exchange.fetch_klines(
                    symbol=symbol,
                    interval=timeframe,
                    limit=self._settings.kline_limit,
                )
                timeframe_frames[timeframe] = add_indicators(frame)

            if allow_notifications:
                await self._send_zone_alerts(symbol, timeframe_frames, state.pushover_zones)

            signal = self._evaluator.evaluate(symbol, timeframe_frames)
            ai_analysis = await self._ai_analyzer.analyze(signal)
            signal = self._evaluator.apply_ai_analysis(signal, ai_analysis)
            signals[symbol] = signal
            updated.append(symbol)

            if allow_notifications:
                previous = state.telegram.get(symbol)
                if self._anti_spam.should_send(signal, previous):
                    message = await self._notifier.send(signal)
                    if message is not None:
                        sent_at = datetime.now(UTC)
                        state.telegram[symbol] = self._state_store.update_telegram_state(symbol, signal, message).telegram[symbol]
                        self._supabase.log_signal(signal, sent_at)
                    elif not self._notifier.is_enabled():
                        logger.info('Telegram disabled; no notification persisted for %s', symbol)

        state.signals = signals
        self._state_store.save(state)
        return updated

    async def _send_zone_alerts(
        self,
        symbol: str,
        timeframe_frames: dict[str, object],
        previous_states: dict[str, PushoverZoneState],
    ) -> None:
        for timeframe, frame in timeframe_frames.items():
            try:
                zones, indicators = build_hybrid_zones(frame)
            except ValueError as exc:
                logger.warning('Pushover zone check skipped for %s %s: %s', symbol, timeframe, exc)
                continue

            active_zone = next((zone for zone in zones if zone.status == 'active'), None)
            key = self._pushover_zone_key(symbol, timeframe)
            previous = previous_states.get(key)
            if active_zone is None:
                updated_state = self._state_store.update_pushover_zone_state(key, None, 'neutral')
                previous_states[key] = updated_state.pushover_zones[key]
                continue

            if not self._zone_rsi_confirmed(active_zone, indicators.rsi_14):
                updated_state = self._state_store.update_pushover_zone_state(key, active_zone.zone_type, 'near')
                previous_states[key] = updated_state.pushover_zones[key]
                logger.info(
                    'Pushover zone alert skipped for %s %s: %s zone active but RSI %.1f not confirmed',
                    symbol,
                    timeframe,
                    active_zone.zone_type,
                    indicators.rsi_14,
                )
                continue

            if not self._should_send_zone_alert(active_zone, previous):
                updated_state = self._state_store.update_pushover_zone_state(key, active_zone.zone_type, active_zone.status)
                previous_states[key] = updated_state.pushover_zones[key]
                continue

            latest = frame.iloc[-1]
            message = await self._pushover.send_zone_alert(
                symbol=symbol,
                timeframe=timeframe,
                price=float(latest['close']),
                zone=active_zone,
                indicators=indicators,
            )
            if message is not None:
                updated_state = self._state_store.update_pushover_zone_state(
                    key,
                    active_zone.zone_type,
                    active_zone.status,
                    message=message,
                    sent=True,
                )
                previous_states[key] = updated_state.pushover_zones[key]
            elif not self._pushover.is_enabled():
                updated_state = self._state_store.update_pushover_zone_state(key, active_zone.zone_type, active_zone.status)
                previous_states[key] = updated_state.pushover_zones[key]

    def _should_send_zone_alert(self, zone: ChartZone, previous: PushoverZoneState | None) -> bool:
        if previous is None or previous.last_zone_type is None:
            return True
        if previous.last_status != 'active':
            return True
        if previous.last_zone_type != zone.zone_type:
            return True
        if previous.last_sent_at is None:
            return True

        elapsed = (datetime.now(UTC) - previous.last_sent_at).total_seconds()
        return elapsed >= self._settings.pushover_zone_cooldown_minutes * 60

    def _zone_rsi_confirmed(self, zone: ChartZone, rsi: float) -> bool:
        if zone.zone_type == 'buy':
            return rsi <= self._settings.pushover_buy_rsi_max
        return rsi >= self._settings.pushover_sell_rsi_min

    @staticmethod
    def _pushover_zone_key(symbol: str, timeframe: str) -> str:
        return f'{symbol.upper()}:{timeframe}'

    def get_signals(self) -> SignalEnvelope:
        state = self._state_store.load()
        return SignalEnvelope(signals=state.signals, updated_at=state.updated_at)

    def get_signal(self, symbol: str) -> SignalState | None:
        return self._state_store.load().signals.get(symbol.upper())

    async def send_startup_status(self, startup_error: str | None = None) -> str | None:
        state = self._state_store.load()
        message = self._notifier.build_startup_message(
            signals=state.signals,
            interval_seconds=self._settings.check_interval_seconds,
            startup_error=startup_error,
        )
        return await self._notifier.send_text(message)

    def _render_ai_chart(
        self,
        symbol: str,
        timeframe_frames: dict[str, object],
        signal: SignalState,
    ) -> bytes | None:
        timeframe = self._chart_renderer.timeframe
        frame = timeframe_frames.get(timeframe)
        if frame is None:
            logger.warning('AI chart skipped for %s: timeframe %s unavailable', symbol, timeframe)
            return None
        try:
            return self._chart_renderer.render_signal_chart(frame, signal)
        except Exception as exc:  # noqa: BLE001
            logger.warning('AI chart render failed for %s %s: %s', symbol, timeframe, exc)
            return None


class BackgroundScheduler:
    def __init__(self, service: SignalService, interval_seconds: int, run_immediately: bool = True) -> None:
        self._service = service
        self._interval_seconds = interval_seconds
        self._run_immediately = run_immediately
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run_forever())
        logger.info('Background scheduler started with interval=%s seconds', self._interval_seconds)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            logger.info('Background scheduler stopped')
        finally:
            self._task = None

    async def _run_forever(self) -> None:
        first_cycle = True
        while True:
            if first_cycle and not self._run_immediately:
                first_cycle = False
                await asyncio.sleep(self._interval_seconds)
            try:
                async with self._lock:
                    updated = await self._service.run_once()
                logger.info('Scheduled analysis cycle completed for symbols=%s', updated)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception('Scheduled analysis cycle failed: %s', exc)
            first_cycle = False
            await asyncio.sleep(self._interval_seconds)
