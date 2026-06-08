from __future__ import annotations

from typing import Literal


Action = Literal['BUY', 'SELL', 'BUY_WATCH', 'SELL_WATCH', 'WAIT_CONFLICT', 'HOLD']
Confidence = Literal['high', 'medium', 'low']

# Volume tối thiểu để xác nhận breakout/breakdown
ENTRY_VOLUME_RATIO = 1.3
# Wick tối thiểu so với body để xác nhận pin bar rejection
PIN_BAR_WICK_RATIO = 2.0


class DecisionEngine:
    # Asymmetric thresholds: SELL khó hơn BUY 2 điểm.
    # Lý do (verify trên 6 năm BTC/ETH 2019-2025):
    #   - BUY_WATCH @ 72:  win-rate 70-72% (đã rất cao, giữ nguyên)
    #   - SELL_WATCH @ 72: win-rate 59-67% (yếu hơn BUY ~5-13 điểm)
    #   - SELL_WATCH @ 74: BTC win-rate 67.5%→74.1% (+6.6pp), mean ret +0.75pp,
    #                      sharpe 0.44→0.58. Số signal giảm 126→58 (chọn lọc).
    # Crypto có upward drift dài hạn → SELL signal cần evidence mạnh hơn.
    BUY_THRESHOLD = 72
    SELL_THRESHOLD = 74
    OPPOSITE_MAX = 45

    @staticmethod
    def decide_action(buy_score: int, sell_score: int) -> Action:
        if buy_score >= DecisionEngine.BUY_THRESHOLD and sell_score <= DecisionEngine.OPPOSITE_MAX:
            return 'BUY_WATCH'
        if sell_score >= DecisionEngine.SELL_THRESHOLD and buy_score <= DecisionEngine.OPPOSITE_MAX:
            return 'SELL_WATCH'
        if buy_score >= 60 and sell_score >= 60:
            return 'WAIT_CONFLICT'
        return 'HOLD'

    @staticmethod
    def decide_confidence(buy_score: int, sell_score: int) -> Confidence:
        dominant = max(buy_score, sell_score)
        opposite = min(buy_score, sell_score)
        if dominant >= 82 and opposite <= 35:
            return 'high'
        if dominant >= 72:
            return 'medium'
        return 'low'

    @staticmethod
    def detect_entry(
        action: Action,
        open_price: float,
        high: float,
        low: float,
        close: float,
        support: float,
        resistance: float,
        volume_ratio: float | None,
    ) -> Action:
        """Nâng BUY_WATCH→BUY hoặc SELL_WATCH→SELL khi nến hiện tại xác nhận entry.

        Có 2 loại xác nhận:
        - Breakout/Breakdown: giá đóng cửa vượt kháng cự/hỗ trợ kèm volume mạnh.
        - Pin bar rejection: nến có wick dài từ chối tại kháng cự/hỗ trợ.
        """
        if action not in ('BUY_WATCH', 'SELL_WATCH'):
            return action

        body = abs(close - open_price)
        vol_ok = volume_ratio is not None and volume_ratio >= ENTRY_VOLUME_RATIO

        if action == 'BUY_WATCH':
            # Breakout: nến đóng cửa trên kháng cự kèm volume
            if close > resistance and vol_ok:
                return 'BUY'
            # Pin bar bullish tại vùng hỗ trợ: lower wick dài, close gần high
            lower_wick = min(open_price, close) - low
            if (
                close <= support * 1.01
                and body > 0
                and lower_wick >= body * PIN_BAR_WICK_RATIO
                and close > open_price  # nến xanh
            ):
                return 'BUY'

        if action == 'SELL_WATCH':
            # Breakdown: nến đóng cửa dưới hỗ trợ kèm volume
            if close < support and vol_ok:
                return 'SELL'
            # Pin bar bearish tại vùng kháng cự: upper wick dài, close gần low
            upper_wick = high - max(open_price, close)
            if (
                close >= resistance * 0.99
                and body > 0
                and upper_wick >= body * PIN_BAR_WICK_RATIO
                and close < open_price  # nến đỏ
            ):
                return 'SELL'

        return action
