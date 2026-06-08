# 9trade

Service gộp đã triển khai theo Phương án A (Co-location) tại `app/`:
- `app/main.py` — FastAPI bootstrap: `lifespan` khởi động cả 2 scheduler, mount router prefix `/ethbot` + `/tradebot`, `/` index + `/health` tổng hợp. Giữ `app_state` ở đây vì `app/tradebot/routes/signals.py` import `from app.main import app_state`.
- `app/ethbot/` — ethbot tách từ `crypto-service-only/app/main.py`: `tracker.py` (indicator + decision + job), `routes.py` (2 dashboard handler dùng `def` đồng bộ để FastAPI dispatch threadpool, không chặn event loop), `scheduler.py` (apscheduler thread riêng), `supabase_logger.py`, `templates/`.
- `app/tradebot/` — copy nguyên `tradebot/app/`, mọi import `app.X`→`app.tradebot.X`; `config.py` có `extra='ignore'` để bỏ qua env của ethbot.
- 2 engine độc lập hoàn toàn: indicator math, decision rule, anti-spam, notify channel (Pushover vs Telegram), AI overlay, action enum đều KHÔNG dùng chung. Chỉ chung HTTP server + Supabase table `signals` (phân biệt bằng cột `bot_source`).
- URL: `/ethbot/ETHUSDT` `/ethbot/BTCUSDT` `/ethbot/bots/*` `/ethbot/health`; `/tradebot/` `/tradebot/signals*` `/tradebot/run-once` `/tradebot/health`; `/` + `/health` ở root.
- `crypto-service-only/` và `tradebot/` giữ lại làm reference/rollback. Verify: import OK + 8 endpoint smoke test trả 200 qua lifespan.

Nguồn gốc 2 bot:
- `crypto-service-only/` — **ethbot**: FastAPI monolithic, sync (requests) + apscheduler, indicators tự viết, dynamic-zone RSI/MACD trên 4h + BTC bull-filter, notify Pushover, dashboard Jinja2, ghi Supabase `bot_source='ethbot'`.
- `tradebot/` — **tradebot**: FastAPI modular, async (httpx) + asyncio scheduler, indicators qua lib `ta`, scoring đa timeframe (1h/4h/1d) + volume confirm + entry detection, OpenAI analyzer, notify Telegram + chart ảnh, dashboard lightweight-charts, ghi Supabase `bot_source='tradebot'`.

## 하네스: Bot Merge Review

**목표:** Review codebase 2 trading bot và lập kế hoạch gộp thành 1 service giữ chức năng độc lập.

**트리거:** Khi có yêu cầu review/so sánh/gộp 2 bot (vd "review 2 bot", "gộp tradebot và ethbot", "lập plan tích hợp", "cập nhật plan gộp"), dùng skill `bot-merge-review`. Câu hỏi đơn giản trả lời trực tiếp.

Chế độ thực thi: sub-agent pattern (môi trường không có TeamCreate). Agent định nghĩa ở `.claude/agents/`, skill ở `.claude/skills/`. Trung gian ghi `_workspace/`.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-06-08 | 초기 구성: 3 agent (architecture-reviewer, signal-logic-reviewer, integration-merge-analyst) + 4 skill (3 review + orchestrator bot-merge-review) | 전체 | Build harness review + plan gộp 2 bot |
| 2026-06-08 | Triển khai Phương án A (Co-location): gộp 2 bot vào `app/` (ethbot + tradebot package độc lập), bootstrap + Dockerfile + koyeb.yaml + requirements union | app/, deployment | Thực thi plan gộp; verify import + 8 endpoint smoke test 200 |
| 2026-06-08 | Build & verify Docker image trên Python 3.11; fix graceful shutdown bằng `exec` trong CMD (PID 1 nhận SIGTERM) | Dockerfile | Container healthy, 8 endpoint 200, concurrency PASS (ethbot sync không chặn loop tradebot), shutdown exit 0 |
