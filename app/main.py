from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler as EthbotScheduler
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.ethbot.routes import bots_router as ethbot_bots_router
from app.ethbot.routes import router as ethbot_router
from app.ethbot.scheduler import start_ethbot_scheduler, stop_ethbot_scheduler
from app.tradebot.config import Settings, get_settings
from app.tradebot.market.exchange import get_exchange_provider
from app.tradebot.routes.dashboard import router as tradebot_dashboard_router
from app.tradebot.routes.health import router as tradebot_health_router
from app.tradebot.routes.signals import router as tradebot_signals_router
from app.tradebot.scheduler import BackgroundScheduler, SignalService
from app.tradebot.storage.state import StateStore

logger = logging.getLogger(__name__)


@dataclass
class AppState:
    settings: Settings
    service: SignalService
    scheduler: BackgroundScheduler


# Giữ tên `app_state` ở module này vì app.tradebot.routes.signals import `from app.main import app_state`.
app_state: AppState


@asynccontextmanager
async def lifespan(_: FastAPI):
    global app_state

    # --- Tradebot init (giữ nguyên flow gốc của tradebot) ---
    settings = get_settings()
    settings.state_path.parent.mkdir(parents=True, exist_ok=True)
    state_store = StateStore(settings.state_path)
    service = SignalService(settings=settings, exchange=get_exchange_provider(settings), state_store=state_store)
    try:
        await service.run_once(allow_notifications=False)
        await service.send_startup_status()
    except Exception as exc:  # noqa: BLE001
        logger.exception('Tradebot startup analysis failed: %s', exc)
        await service.send_startup_status(startup_error=str(exc))
    tradebot_sched = BackgroundScheduler(
        service=service,
        interval_seconds=settings.check_interval_seconds,
        run_immediately=False,
    )
    app_state = AppState(settings=settings, service=service, scheduler=tradebot_sched)
    await tradebot_sched.start()

    # --- Ethbot init: apscheduler trên thread riêng, KHÔNG vào event loop ---
    eth_sched: EthbotScheduler | None = None
    try:
        eth_sched = start_ethbot_scheduler()
    except Exception as exc:  # noqa: BLE001
        logger.exception('Ethbot scheduler failed to start: %s', exc)

    try:
        yield
    finally:
        await tradebot_sched.stop()
        if eth_sched is not None:
            stop_ethbot_scheduler(eth_sched)


settings = get_settings()
app = FastAPI(title='9trade unified (ethbot + tradebot)', lifespan=lifespan)

# Mount ethbot dưới prefix /ethbot — giữ dashboard Jinja2/Chart.js độc lập
app.include_router(ethbot_router, prefix='/ethbot')
app.include_router(ethbot_bots_router, prefix='/ethbot')

# Mount tradebot dưới prefix /tradebot — giữ dashboard lightweight-charts độc lập
app.include_router(tradebot_dashboard_router, prefix='/tradebot')
app.include_router(tradebot_signals_router, prefix='/tradebot')
app.include_router(tradebot_health_router, prefix='/tradebot')


@app.get('/')
def index():
    return RedirectResponse(url='/tradebot/', status_code=307)


@app.get('/health')
def health():
    return {
        'ok': True,
        'service': '9trade-unified',
        'time_utc': datetime.utcnow().isoformat() + 'Z',
        'bots': ['ethbot', 'tradebot'],
    }
