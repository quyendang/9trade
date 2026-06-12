from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.tradebot.config import Settings, get_settings
from app.tradebot.market.exchange import get_exchange_provider
from app.tradebot.market.indicators import add_indicators, latest_snapshot
from app.tradebot.market.order_book import build_order_book_walls
from app.tradebot.market.zones import build_chart_candles, build_hybrid_zones
from app.tradebot.models.schema import (
    ChartDataResponse,
    IndicatorTestResponse,
    RunOnceResponse,
    SignalEnvelope,
    SignalState,
    SymbolIndicatorResponse,
)
from app.tradebot.scheduler import SignalService
from app.tradebot.storage.state import StateStore

logger = logging.getLogger(__name__)
router = APIRouter(tags=['signals'])


@router.get('/signals/test', response_model=IndicatorTestResponse)
async def test_indicators(settings: Settings = Depends(get_settings)) -> IndicatorTestResponse:
    exchange = get_exchange_provider(settings)
    response = IndicatorTestResponse(provider=settings.exchange_provider)

    for symbol in settings.default_symbols:
        symbol_payload = SymbolIndicatorResponse(symbol=symbol)
        for timeframe in settings.default_timeframes:
            frame = await exchange.fetch_klines(symbol=symbol, interval=timeframe, limit=settings.kline_limit)
            enriched = add_indicators(frame)
            symbol_payload.timeframes[timeframe] = latest_snapshot(symbol, timeframe, enriched)
        response.symbols[symbol] = symbol_payload

    return response


def get_signal_service(settings: Settings = Depends(get_settings)) -> SignalService:
    try:
        from app.main import app_state

        return app_state.service
    except Exception:
        state_store = StateStore(settings.state_path)
        exchange = get_exchange_provider(settings)
        return SignalService(settings=settings, exchange=exchange, state_store=state_store)


@router.get('/signals', response_model=SignalEnvelope)
def get_signals(service: SignalService = Depends(get_signal_service)) -> SignalEnvelope:
    return service.get_signals()


@router.get('/signals/{symbol}', response_model=SignalState)
def get_signal(symbol: str, service: SignalService = Depends(get_signal_service)) -> SignalState:
    signal = service.get_signal(symbol)
    if signal is None:
        raise HTTPException(status_code=404, detail='Signal not found')
    return signal


@router.post('/run-once', response_model=RunOnceResponse)
async def run_once(service: SignalService = Depends(get_signal_service)) -> RunOnceResponse:
    updated = await service.run_once()
    return RunOnceResponse(status='ok', updated_symbols=updated, detail='Technical analysis cycle completed')


@router.get('/chart-data/{symbol}', response_model=ChartDataResponse)
async def chart_data(
    symbol: str,
    timeframe: Annotated[Literal['1h', '4h', '1d'], Query()] = '4h',
    limit: Annotated[int, Query(ge=80, le=500)] = 300,
    settings: Settings = Depends(get_settings),
    service: SignalService = Depends(get_signal_service),
) -> ChartDataResponse:
    symbol = symbol.upper()
    if symbol not in {configured.upper() for configured in settings.default_symbols}:
        raise HTTPException(status_code=404, detail='Symbol not configured')

    try:
        exchange = get_exchange_provider(settings)
        frame = await exchange.fetch_klines(symbol=symbol, interval=timeframe, limit=limit)
        enriched = add_indicators(frame)
        zones, indicators = build_hybrid_zones(enriched)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    walls = []
    if settings.order_book_walls_enabled:
        try:
            order_book = await exchange.fetch_order_book(symbol=symbol, limit=settings.order_book_depth_limit)
            current_price = float(enriched.iloc[-1]['close'])
            walls = build_order_book_walls(
                order_book=order_book,
                current_price=current_price,
                bucket_pct=settings.order_book_wall_bucket_pct,
                min_quote=settings.order_book_wall_min_quote,
                max_levels=settings.order_book_wall_max_levels,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning('Order book walls unavailable for %s: %s', symbol, exc)

    return ChartDataResponse(
        symbol=symbol,
        timeframe=timeframe,
        candles=build_chart_candles(enriched),
        zones=zones,
        order_book_walls=walls,
        latest_indicators=indicators,
        current_signal=service.get_signal(symbol),
    )
