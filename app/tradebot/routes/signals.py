from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.tradebot.config import Settings, get_settings
from app.tradebot.market.exchange import get_exchange_provider
from app.tradebot.market.indicators import add_indicators, latest_snapshot
from app.tradebot.models.schema import (
    IndicatorTestResponse,
    RunOnceResponse,
    SignalEnvelope,
    SignalState,
    SymbolIndicatorResponse,
)
from app.tradebot.scheduler import SignalService
from app.tradebot.storage.state import StateStore

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
