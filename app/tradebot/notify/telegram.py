from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.tradebot.config import Settings
from app.tradebot.models.schema import SignalState

logger = logging.getLogger(__name__)


def _fmt_duration(seconds: float) -> str:
    if seconds <= 0:
        return 'đã đóng'
    m = int(seconds // 60)
    if m == 0:
        return '<1p'
    if m < 60:
        return f'{m}p'
    h, rem = divmod(m, 60)
    return f'{h}g{rem:02d}p' if rem else f'{h}g'


class TelegramNotifier:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_enabled(self) -> bool:
        return bool(self._settings.telegram_bot_token and self._settings.telegram_chat_id)

    def build_message(self, signal: SignalState) -> str:
        risks = self._format_list(signal.ai_analysis.risk_notes, default='Không có')
        conflicts = self._format_list(signal.ai_analysis.conflicts, default='Không có')
        dominant_score = max(signal.buy_score, signal.sell_score)
        dominant_side = 'Mua' if signal.buy_score >= signal.sell_score else 'Bán'
        return (
            f'Tradebot | {signal.symbol}\n'
            f'Tín hiệu: {self._action_label(signal.action)}\n'
            f'Độ tin cậy: {self._confidence_label(signal.confidence)}\n'
            f'Giá hiện tại: {signal.price:.2f}\n'
            f'Điểm ưu thế: {dominant_side} ({dominant_score})\n'
            f'Điểm Mua/Bán: {signal.buy_score}/{signal.sell_score}\n'
            f'Hỗ trợ: {signal.support:.2f}\n'
            f'Kháng cự: {signal.resistance:.2f}\n'
            f'Mốc vô hiệu: {signal.invalidation:.2f}\n'
            f'Nến đóng sau: {self._format_candle_countdowns(signal)}\n'
            f'Vùng mua: {self._format_zone(signal.buy_zone)}\n'
            f'Vùng bán: {self._format_zone(signal.sell_zone)}\n'
            f'\n'
            f'Tóm tắt AI:\n{signal.ai_analysis.summary}\n'
            f'\n'
            f'Ghi chú nhanh:\n{signal.ai_analysis.telegram_note}\n'
            f'\n'
            f'Rủi ro:\n{risks}\n'
            f'\n'
            f'Xung đột:\n{conflicts}'
        )

    def build_startup_message(
        self,
        signals: dict[str, SignalState],
        interval_seconds: int,
        startup_error: str | None = None,
    ) -> str:
        lines = [
            'Tradebot đã khởi động',
            f'Chu kỳ quét: {interval_seconds}s',
            f'OpenAI: {"đã cấu hình" if self._settings.openai_api_key else "chưa cấu hình"}',
        ]

        if startup_error is not None:
            lines.append(f'Lỗi phân tích ban đầu: {startup_error}')
            return '\n'.join(lines)

        if not signals:
            lines.append('Phân tích ban đầu: chưa có dữ liệu')
            return '\n'.join(lines)

        lines.append('Phân tích ban đầu:')
        for symbol in sorted(signals):
            signal = signals[symbol]
            ai_status = self._ai_status_label(signal)
            lines.append('')
            lines.append(f'• {signal.symbol}')
            lines.append(f'  - Tín hiệu: {self._action_label(signal.action)}')
            lines.append(f'  - Độ tin cậy: {self._confidence_label(signal.confidence)}')
            lines.append(f'  - Điểm Mua/Bán: {signal.buy_score}/{signal.sell_score}')
            lines.append(f'  - AI: {ai_status}')
            lines.append(f'  - Vùng mua: {self._format_zone(signal.buy_zone)}')
            lines.append(f'  - Vùng bán: {self._format_zone(signal.sell_zone)}')
            lines.append(f'  - Ghi chú: {signal.ai_analysis.telegram_note}')

        return '\n'.join(lines)

    @staticmethod
    def _format_list(items: list[str], default: str) -> str:
        if not items:
            return default
        return '\n'.join(f'- {item}' for item in items[:3])

    @staticmethod
    def _action_label(action: str) -> str:
        labels = {
            'BUY': '🟢 VÀO LỆNH MUA',
            'SELL': '🔴 VÀO LỆNH BÁN',
            'BUY_WATCH': 'Theo dõi Mua',
            'SELL_WATCH': 'Theo dõi Bán',
            'WAIT_CONFLICT': 'Chờ xác nhận',
            'HOLD': 'Đứng quan sát',
        }
        return labels.get(action, action)

    @staticmethod
    def _confidence_label(confidence: str) -> str:
        labels = {
            'high': 'Cao',
            'medium': 'Trung bình',
            'low': 'Thấp',
        }
        return labels.get(confidence, confidence)

    @staticmethod
    def _ai_status_label(signal: SignalState) -> str:
        if signal.ai_analysis.data_quality_warning:
            return 'Cảnh báo dữ liệu'
        if signal.ai_analysis.summary == 'AI analysis unavailable':
            return 'Không khả dụng'
        return 'Bình thường'

    @staticmethod
    def _format_candle_countdowns(signal: SignalState) -> str:
        now = datetime.now(timezone.utc)
        parts = []
        for ts in signal.timeframe_scores:
            secs = (ts.indicators.close_time - now).total_seconds()
            parts.append(f'{ts.timeframe}={_fmt_duration(secs)}')
        return ' | '.join(parts) if parts else 'N/A'

    @staticmethod
    def _format_zone(zone) -> str:
        if zone is None:
            return 'Chưa có'
        return f'{zone.low:.2f} - {zone.high:.2f}\n  ↳ {zone.note}'

    async def send_text(self, text: str) -> str | None:
        if not self.is_enabled():
            logger.info('Telegram not configured, skipping text notification')
            return None

        payload = {
            'chat_id': self._settings.telegram_chat_id,
            'text': text,
        }
        url = f'https://api.telegram.org/bot{self._settings.telegram_bot_token}/sendMessage'
        timeout = httpx.Timeout(self._settings.request_timeout_seconds)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
            return payload['text']
        except Exception as exc:  # noqa: BLE001
            logger.warning('Telegram startup/status send failed: %s', exc)
            return None

    async def send(self, signal: SignalState) -> str | None:
        if not self.is_enabled():
            logger.info('Telegram not configured, skipping notification for %s', signal.symbol)
            return None
        return await self.send_text(self.build_message(signal))
