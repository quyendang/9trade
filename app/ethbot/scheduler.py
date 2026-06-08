import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.ethbot.tracker import TRACKER_CHECK_MINUTES, rsi_check_once, symbols_tracker_job

logger = logging.getLogger(__name__)


def start_ethbot_scheduler() -> BackgroundScheduler:
    """Khởi động scheduler riêng của ethbot trên worker thread (apscheduler).

    Chạy ngoài event loop nên job sync `requests` không chặn loop của tradebot.
    """
    rsi_check_once()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        symbols_tracker_job,
        "interval",
        minutes=TRACKER_CHECK_MINUTES,
        id="symbols_tracker_job",
        replace_existing=True,
        next_run_time=datetime.utcnow(),
    )
    scheduler.start()
    logger.info("[ethbot] scheduler started, interval=%s minutes", TRACKER_CHECK_MINUTES)
    return scheduler


def stop_ethbot_scheduler(scheduler: BackgroundScheduler) -> None:
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[ethbot] scheduler stopped")
