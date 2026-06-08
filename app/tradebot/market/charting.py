from __future__ import annotations

import io
import os

os.environ.setdefault('MPLCONFIGDIR', '/tmp/matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from app.tradebot.models.schema import SignalState


class ChartRenderer:
    def __init__(self, timeframe: str = '4h', candle_limit: int = 140) -> None:
        self._timeframe = timeframe
        self._candle_limit = candle_limit

    @property
    def timeframe(self) -> str:
        return self._timeframe

    def render_signal_chart(self, frame: pd.DataFrame, signal: SignalState) -> bytes:
        if frame.empty:
            raise ValueError(f'Cannot render chart for {signal.symbol}: empty frame')

        chart_frame = frame.tail(self._candle_limit).copy()
        if 'open_time' not in chart_frame.columns:
            raise ValueError('Chart frame missing open_time column')

        chart_frame['open_time'] = pd.to_datetime(chart_frame['open_time'], utc=True).dt.tz_localize(None)
        chart_frame = chart_frame.set_index('open_time')

        market_frame = chart_frame[['open', 'high', 'low', 'close', 'volume']].copy()
        overlays = [
            mpf.make_addplot(chart_frame['ema_50'], color='#f59e0b', width=1.1),
            mpf.make_addplot(chart_frame['ema_200'], color='#60a5fa', width=1.1),
            mpf.make_addplot(chart_frame['bollinger_upper'], color='#94a3b8', width=0.9, linestyle='dashdot'),
            mpf.make_addplot(chart_frame['bollinger_middle'], color='#cbd5e1', width=0.8, linestyle='dashed'),
            mpf.make_addplot(chart_frame['bollinger_lower'], color='#94a3b8', width=0.9, linestyle='dashdot'),
            mpf.make_addplot(chart_frame['rsi_14'], panel=1, color='#f97316', width=1.0),
            mpf.make_addplot(chart_frame['macd'], panel=2, color='#22c55e', width=1.0),
            mpf.make_addplot(chart_frame['macd_signal'], panel=2, color='#ef4444', width=1.0),
            mpf.make_addplot(
                chart_frame['macd_histogram'],
                panel=2,
                type='bar',
                width=0.7,
                color=[
                    '#22c55e' if value >= 0 else '#ef4444'
                    for value in chart_frame['macd_histogram'].fillna(0.0)
                ],
                alpha=0.75,
            ),
        ]

        style = mpf.make_mpf_style(
            base_mpf_style='charles',
            facecolor='#0f172a',
            figcolor='#0f172a',
            edgecolor='#334155',
            gridcolor='#1e293b',
            gridstyle=':',
            y_on_right=False,
            rc={
                'axes.labelcolor': '#e2e8f0',
                'axes.edgecolor': '#334155',
                'xtick.color': '#cbd5e1',
                'ytick.color': '#cbd5e1',
                'axes.titlecolor': '#f8fafc',
                'figure.titlesize': 14,
            },
            marketcolors=mpf.make_marketcolors(
                up='#22c55e',
                down='#ef4444',
                wick='inherit',
                edge='inherit',
                volume='inherit',
            ),
        )

        fig, axes = mpf.plot(
            market_frame,
            type='candle',
            style=style,
            addplot=overlays,
            panel_ratios=(6, 2, 2),
            figsize=(14, 10),
            tight_layout=True,
            returnfig=True,
            xrotation=0,
            ylabel='Price',
            ylabel_lower='MACD',
            title=self._title(signal),
        )

        price_ax = axes[0]
        rsi_ax = axes[2]
        macd_ax = axes[4]

        price_ax.axhline(signal.support, color='#22c55e', linestyle='dashed', linewidth=0.9, alpha=0.85)
        price_ax.axhline(signal.resistance, color='#f97316', linestyle='dashed', linewidth=0.9, alpha=0.85)
        price_ax.axhline(signal.invalidation, color='#f43f5e', linestyle='dotted', linewidth=1.0, alpha=0.9)

        if signal.buy_zone is not None:
            price_ax.axhspan(signal.buy_zone.low, signal.buy_zone.high, color='#16a34a', alpha=0.12)
        if signal.sell_zone is not None:
            price_ax.axhspan(signal.sell_zone.low, signal.sell_zone.high, color='#dc2626', alpha=0.12)

        rsi_ax.axhline(70, color='#64748b', linestyle='dashed', linewidth=0.8)
        rsi_ax.axhline(30, color='#64748b', linestyle='dashed', linewidth=0.8)
        rsi_ax.set_ylabel('RSI', color='#e2e8f0')

        macd_ax.axhline(0, color='#64748b', linestyle='dashed', linewidth=0.8)
        macd_ax.set_ylabel('MACD', color='#e2e8f0')

        summary = (
            f'Action: {signal.action}\n'
            f'Confidence: {signal.confidence}\n'
            f'Buy/Sell: {signal.buy_score}/{signal.sell_score}\n'
            f'Support: {signal.support:.2f}\n'
            f'Resistance: {signal.resistance:.2f}'
        )
        price_ax.text(
            0.015,
            0.98,
            summary,
            transform=price_ax.transAxes,
            va='top',
            ha='left',
            color='#f8fafc',
            fontsize=9,
            bbox={
                'boxstyle': 'round,pad=0.45',
                'facecolor': '#020617',
                'edgecolor': '#334155',
                'alpha': 0.85,
            },
        )

        buffer = io.BytesIO()
        fig.savefig(buffer, format='png', dpi=140, bbox_inches='tight')
        plt.close(fig)
        buffer.seek(0)
        return buffer.getvalue()

    def _title(self, signal: SignalState) -> str:
        return (
            f'{signal.symbol} {self._timeframe} | '
            f'{signal.action} | {signal.confidence.upper()} | '
            f'Buy {signal.buy_score} / Sell {signal.sell_score}'
        )
