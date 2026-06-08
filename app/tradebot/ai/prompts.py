from __future__ import annotations

_JSON_SCHEMA = '''{
  "summary": "<tóm tắt ngắn gọn tín hiệu bằng tiếng Việt>",
  "risk_notes": ["<rủi ro 1>", "<rủi ro 2>"],
  "conflicts": ["<xung đột tín hiệu 1>"],
  "telegram_note": "<ghi chú ngắn cho Telegram bằng tiếng Việt>",
  "data_quality_warning": false
}'''

SYSTEM_PROMPT = (
    'You are an auxiliary crypto market analyst. '
    'You must not make or change trade decisions. '
    'You only summarize the existing technical decision, identify risks and conflicts, '
    'use any attached chart screenshot only as supporting context, '
    'and flag actual data quality problems. '
    'Always write in Vietnamese with full accents, concise and easy to read for Telegram.\n'
    'You MUST respond with ONLY a valid JSON object. No explanation, no markdown, no code fences.\n'
    f'Use exactly this structure:\n{_JSON_SCHEMA}'
)


def build_user_prompt(snapshot: dict) -> str:
    s = snapshot
    tfs = s.get('timeframes', [])
    tf_lines = ' | '.join(
        f"{t['timeframe']} buy={t['buy_score']} sell={t['sell_score']} rsi={t.get('rsi_14', '?'):.1f}"
        for t in tfs
    )
    reasons = '; '.join(s.get('reasons', [])[:4])
    body = (
        f"Symbol={s['symbol']} Action={s['action']} Confidence={s.get('confidence','?')} "
        f"Buy={s['buy_score']} Sell={s['sell_score']} Price={s['price']} "
        f"Support={s['support']} Resistance={s['resistance']}\n"
        f"Timeframes: {tf_lines}\n"
        f"Reasons: {reasons}"
    )
    return f'Signal:\n{body}\nRespond with ONLY the JSON object.'
