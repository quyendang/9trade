from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.tradebot.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=['dashboard'])


def _get_supabase_signals(settings: Settings) -> list[dict]:
    if not settings.supabase_url or not settings.supabase_key:
        return []
    try:
        from supabase import create_client
        client = create_client(settings.supabase_url, settings.supabase_key)
        result = client.table('signals').select(
            'symbol,action,confidence,buy_score,sell_score,price,support,resistance,invalidation,sent_at,as_of,bot_source'
        ).order('sent_at', desc=False).execute()
        return result.data or []
    except Exception as exc:
        logger.warning('Failed to fetch signals from Supabase: %s', exc)
        return []


def _parse_ts(raw: str) -> int | None:
    if not raw:
        return None
    try:
        raw = raw.replace('Z', '+00:00')
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _signals_to_js(signals: list[dict], symbols: list[str]) -> str:
    grouped: dict[str, list[dict]] = {s: [] for s in symbols}
    for row in signals:
        sym = row.get('symbol', '').upper()
        if sym not in grouped:
            continue
        ts = _parse_ts(row.get('sent_at') or row.get('as_of') or '')
        if ts is None:
            continue
        grouped[sym].append({
            'time': ts,
            'action': row.get('action', ''),
            'confidence': row.get('confidence', ''),
            'buy_score': row.get('buy_score', 0),
            'sell_score': row.get('sell_score', 0),
            'price': row.get('price', 0),
            'support': row.get('support', 0),
            'resistance': row.get('resistance', 0),
            'bot_source': row.get('bot_source') or 'tradebot',
        })
    return json.dumps(grouped)


@router.get('/', response_class=HTMLResponse)
async def dashboard(request: Request, settings: Settings = Depends(get_settings)) -> HTMLResponse:
    signals = _get_supabase_signals(settings)
    symbols = [symbol.upper() for symbol in settings.default_symbols]
    signals_json = _signals_to_js(signals, symbols)
    html = _render_html(symbols, signals_json)
    return HTMLResponse(content=html)


def _render_html(symbols: list[str], signals_json: str) -> str:
    current_tf_json = json.dumps({symbol: '4h' for symbol in symbols})
    chart_cards = '\n'.join(
        f"""
    <div class="chart-card">
      <div class="chart-header">
        <span class="chart-title">{symbol}</span>
        <div class="tf-btns" id="tf-{symbol}">
          <button class="tf-btn" data-sym="{symbol}" data-tf="1h">1H</button>
          <button class="tf-btn active" data-sym="{symbol}" data-tf="4h">4H</button>
          <button class="tf-btn" data-sym="{symbol}" data-tf="1d">1D</button>
        </div>
        <span class="chart-price" id="price-{symbol}">—</span>
      </div>
      <div class="chart-body" id="chart-{symbol}"><div class="loading">Đang tải...</div></div>
      <div class="legend" id="legend-{symbol}"></div>
    </div>"""
        for symbol in symbols
    )
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Tradebot Dashboard</title>
  <script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0f172a;
      color: #e2e8f0;
      font-family: system-ui, sans-serif;
      min-height: 100vh;
      padding: 24px 16px;
    }}
    h1 {{ font-size: 1.2rem; font-weight: 600; color: #f8fafc; margin-bottom: 4px; }}
    .subtitle {{ font-size: 0.8rem; color: #64748b; margin-bottom: 20px; }}
    .charts-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }}
    @media (max-width: 900px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}
    .chart-card {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 12px;
      overflow: hidden;
    }}
    .chart-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px 8px;
      border-bottom: 1px solid #334155;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .chart-title {{ font-size: 0.95rem; font-weight: 600; color: #f1f5f9; }}
    .chart-price {{ font-size: 0.85rem; color: #94a3b8; }}
    .tf-btns {{ display: flex; gap: 6px; }}
    .tf-btn {{
      background: #0f172a;
      border: 1px solid #334155;
      color: #94a3b8;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 3px 10px;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.15s;
    }}
    .tf-btn:hover {{ border-color: #60a5fa; color: #60a5fa; }}
    .tf-btn.active {{ background: #1d4ed8; border-color: #3b82f6; color: #fff; }}
    .chart-body {{ position: relative; height: 400px; }}
    .legend {{
      display: flex;
      gap: 14px;
      padding: 8px 16px;
      border-top: 1px solid #334155;
      flex-wrap: wrap;
    }}
    .legend-item {{
      display: flex; align-items: center;
      gap: 5px; font-size: 0.72rem; color: #94a3b8;
    }}
    .legend-dot {{
      width: 9px; height: 9px;
      border-radius: 50%; flex-shrink: 0;
    }}
    .signal-table-wrap {{ margin-top: 28px; }}
    .signal-table-wrap h2 {{ font-size: 1rem; font-weight: 600; color: #f1f5f9; margin-bottom: 12px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.8rem; }}
    th {{
      text-align: left; padding: 8px 12px;
      background: #1e293b; color: #64748b;
      font-weight: 500; border-bottom: 1px solid #334155;
    }}
    td {{ padding: 8px 12px; border-bottom: 1px solid #1e293b; color: #cbd5e1; }}
    tr:hover td {{ background: #1e293b; }}
    .badge {{
      display: inline-block; padding: 2px 8px;
      border-radius: 999px; font-size: 0.72rem; font-weight: 600;
    }}
    .source-badge {{
      display: inline-block; padding: 1px 7px;
      border-radius: 4px; font-size: 0.68rem; font-weight: 600;
    }}
    .loading {{
      display: flex; align-items: center; justify-content: center;
      height: 100%; color: #475569; font-size: 0.85rem;
    }}
  </style>
</head>
<body>
  <h1>Tradebot Dashboard</h1>
  <p class="subtitle">
    Mua <span style="color:#22c55e">●</span> &nbsp; Bán <span style="color:#ef4444">●</span>
    &nbsp;·&nbsp; Buy zone <span style="color:#16a34a">▰</span> &nbsp; Sell zone <span style="color:#dc2626">▰</span>
  </p>

  <div class="charts-grid">
{chart_cards}
  </div>

  <div class="signal-table-wrap">
    <h2>Lịch sử tín hiệu</h2>
    <table>
      <thead>
        <tr>
          <th>Thời gian (UTC)</th>
          <th>Symbol</th>
          <th>Tín hiệu</th>
          <th>Độ tin cậy</th>
          <th>Mua / Bán</th>
          <th>Giá</th>
          <th>Hỗ trợ</th>
          <th>Kháng cự</th>
        </tr>
      </thead>
      <tbody id="signal-tbody"></tbody>
    </table>
  </div>

<script>
const ALL_SIGNALS = {signals_json};
const SYMBOLS = {json.dumps(symbols)};

// action → màu chấm
const ACTION_COLOR = {{
  BUY_WATCH:     '#22c55e',
  SELL_WATCH:    '#ef4444',
  WAIT_CONFLICT: '#f59e0b',
  HOLD:          '#475569',
  BUY:           '#34d399',
  SELL:          '#f87171',
}};
const ACTION_LABEL = {{
  BUY_WATCH: 'Theo dõi Mua', SELL_WATCH: 'Theo dõi Bán',
  WAIT_CONFLICT: 'Chờ xác nhận', HOLD: 'Đứng quan sát',
  BUY: 'Mua', SELL: 'Bán',
}};
const CONF_LABEL = {{ high: 'Cao', medium: 'Trung bình', low: 'Thấp' }};

// Trạng thái timeframe hiện tại của mỗi symbol
const currentTf = {current_tf_json};
// Lưu chart instance để destroy khi đổi TF
const chartInstances = {{}};

function formatPrice(p) {{
  if (!p) return '—';
  return p >= 1000
    ? p.toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 2}})
    : p.toFixed(4);
}}

function formatTime(ts) {{
  const d = new Date(ts * 1000);
  const p = n => String(n).padStart(2, '0');
  return `${{d.getUTCFullYear()}}-${{p(d.getUTCMonth()+1)}}-${{p(d.getUTCDate())}} ${{p(d.getUTCHours())}}:${{p(d.getUTCMinutes())}}`;
}}

async function fetchChartData(symbol, interval, limit) {{
  const url = `/tradebot/chart-data/${{symbol}}?timeframe=${{interval}}&limit=${{limit}}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Chart data ${{res.status}}`);
  return await res.json();
}}

// Snap signal timestamp đến nến gần nhất (tránh lệch múi giờ)
function snapToCandle(sigTs, candles, tfInterval) {{
  const tfSecs = {{ '1h': 3600, '4h': 14400, '1d': 86400 }};
  const step = tfSecs[tfInterval] || 14400;
  // Tìm nến có time <= sigTs gần nhất
  let best = candles[0];
  for (const c of candles) {{
    if (c.time <= sigTs) best = c;
    else break;
  }}
  return best ? best.time : sigTs;
}}

function drawZoneBands(container, chart, candleSeries, zones) {{
  container._zoneBands = [];
  zones.forEach(zone => {{
    const band = document.createElement('div');
    const color = zone.zone_type === 'buy' ? 'rgba(22, 163, 74, 0.16)' : 'rgba(220, 38, 38, 0.14)';
    const border = zone.zone_type === 'buy' ? 'rgba(34, 197, 94, 0.45)' : 'rgba(248, 113, 113, 0.45)';
    band.dataset.low = zone.low;
    band.dataset.high = zone.high;
    band.title = zone.note || '';
    band.style.cssText = `
      position:absolute; left:0; right:0; display:none; z-index:1;
      background:${{color}}; border-top:1px solid ${{border}}; border-bottom:1px solid ${{border}};
      pointer-events:none;
    `;
    container.appendChild(band);
    container._zoneBands.push(band);
  }});

  chart.timeScale().subscribeVisibleTimeRangeChange(() => updateZoneBands(container, candleSeries));
  requestAnimationFrame(() => updateZoneBands(container, candleSeries));
}}

function updateZoneBands(container, candleSeries) {{
  if (!container._zoneBands) return;
  container._zoneBands.forEach(band => {{
    const low = Number(band.dataset.low);
    const high = Number(band.dataset.high);
    const yLow = candleSeries.priceToCoordinate(low);
    const yHigh = candleSeries.priceToCoordinate(high);
    if (yLow == null || yHigh == null) {{
      band.style.display = 'none';
      return;
    }}
    const top = Math.min(yLow, yHigh);
    const height = Math.max(2, Math.abs(yLow - yHigh));
    band.style.top = `${{top}}px`;
    band.style.height = `${{height}}px`;
    band.style.display = 'block';
  }});
}}

function buildChart(symbol, chartData, signals, tf) {{
  const container = document.getElementById(`chart-${{symbol}}`);
  const candles = chartData.candles || [];
  if (candles.length === 0) {{
    container.innerHTML = '<div class="loading">Không có dữ liệu nến</div>';
    return;
  }}

  // Destroy chart cũ nếu có
  if (chartInstances[symbol]) {{
    chartInstances[symbol].remove();
    chartInstances[symbol] = null;
  }}
  container.innerHTML = '';

  const chart = LightweightCharts.createChart(container, {{
    layout: {{ background: {{ color: '#1e293b' }}, textColor: '#94a3b8' }},
    grid:   {{ vertLines: {{ color: '#334155' }}, horzLines: {{ color: '#334155' }} }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    rightPriceScale: {{ borderColor: '#334155' }},
    timeScale: {{ borderColor: '#334155', timeVisible: true, secondsVisible: false }},
    width:  container.clientWidth,
    height: container.clientHeight,
  }});
  chartInstances[symbol] = chart;

  // Nến
  const candleSeries = chart.addCandlestickSeries({{
    upColor: '#22c55e', downColor: '#ef4444',
    borderUpColor: '#22c55e', borderDownColor: '#ef4444',
    wickUpColor: '#22c55e', wickDownColor: '#ef4444',
  }});
  candleSeries.setData(candles);
  drawZoneBands(container, chart, candleSeries, chartData.zones || []);

  // Giá hiện tại
  const last = candles[candles.length - 1];
  document.getElementById(`price-${{symbol}}`).textContent = formatPrice(last.close);

  // Vẽ mỗi signal là 1 chấm tròn (circle) trên đúng nến
  const validSignals = signals.filter(s => s.action !== 'HOLD');
  const markers = validSignals.map(sig => {{
    const color = ACTION_COLOR[sig.action] || '#94a3b8';
    const isBuy = ['BUY_WATCH', 'BUY'].includes(sig.action);
    const snappedTime = snapToCandle(sig.time, candles, tf);
    return {{
      time:     snappedTime,
      position: isBuy ? 'belowBar' : 'aboveBar',
      color:    color,
      shape:    'circle',
      size:     1.4,
      text:     '',   // không text, chỉ chấm
    }};
  }});

  if (markers.length > 0) {{
    // sort by time (required by lightweight-charts)
    markers.sort((a, b) => a.time - b.time);
    candleSeries.setMarkers(markers);
  }}

  // Price lines support/resistance từ backend chart context
  const ind = chartData.latest_indicators || null;
  if (ind) {{
    if (ind.support)    candleSeries.createPriceLine({{ price: ind.support,    color: '#22c55e', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: 'Support' }});
    if (ind.resistance) candleSeries.createPriceLine({{ price: ind.resistance, color: '#f97316', lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: 'Resistance' }});
  }}

  chart.timeScale().fitContent();

  // ── Tooltip khi hover gần chấm signal ──────────────────────────────────
  // Tạo div tooltip gắn vào container
  const tooltip = document.createElement('div');
  tooltip.style.cssText = `
    position:absolute; display:none; z-index:100;
    background:#0f172a; border:1px solid #334155; border-radius:8px;
    padding:10px 14px; font-size:0.78rem; color:#e2e8f0;
    pointer-events:none; min-width:180px; line-height:1.6;
    box-shadow:0 4px 16px rgba(0,0,0,0.5);
  `;
  container.style.position = 'relative';
  container.appendChild(tooltip);

  // Map snappedTime → list of signals tại nến đó
  const sigByTime = {{}};
  validSignals.forEach(sig => {{
    const t = snapToCandle(sig.time, candles, tf);
    if (!sigByTime[t]) sigByTime[t] = [];
    sigByTime[t].push(sig);
  }});

  chart.subscribeCrosshairMove(param => {{
    if (!param.time || !param.point) {{
      tooltip.style.display = 'none';
      return;
    }}
    const sigsAtTime = sigByTime[param.time];
    if (!sigsAtTime || sigsAtTime.length === 0) {{
      tooltip.style.display = 'none';
      return;
    }}

    // Build nội dung tooltip
    const lines = sigsAtTime.map(sig => {{
      const color    = ACTION_COLOR[sig.action] || '#94a3b8';
      const label    = ACTION_LABEL[sig.action] || sig.action;
      const score    = (sig.buy_score || sig.sell_score) ? ` · B${{sig.buy_score}}/S${{sig.sell_score}}` : '';
      const conf     = CONF_LABEL[sig.confidence] || sig.confidence || '';
      return `<div style="margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid #1e293b">
        <span style="color:${{color}};font-weight:700">${{label}}</span><br>
        <span style="color:#94a3b8">Giá:</span> <strong style="color:#f1f5f9">${{formatPrice(sig.price)}}</strong>${{score}}<br>
        <span style="color:#94a3b8">Hỗ trợ:</span> <span style="color:#22c55e">${{formatPrice(sig.support)}}</span>
        &nbsp;<span style="color:#94a3b8">Kháng cự:</span> <span style="color:#f97316">${{formatPrice(sig.resistance)}}</span><br>
        ${{conf ? `<span style="color:#94a3b8">Tin cậy:</span> ${{conf}}<br>` : ''}}
        <span style="color:#475569;font-size:0.7rem">${{formatTime(sig.time)}} UTC</span>
      </div>`;
    }}).join('');

    tooltip.innerHTML = lines;
    tooltip.style.display = 'block';

    // Vị trí tooltip — tránh tràn ra ngoài container
    const cw = container.clientWidth;
    const ch = container.clientHeight;
    let left = param.point.x + 14;
    let top  = param.point.y - 10;
    // Ước tính chiều rộng tooltip ~200px
    if (left + 210 > cw) left = param.point.x - 224;
    if (top + tooltip.offsetHeight > ch) top = ch - tooltip.offsetHeight - 8;
    if (top < 4) top = 4;
    tooltip.style.left = left + 'px';
    tooltip.style.top  = top  + 'px';
  }});
  // ────────────────────────────────────────────────────────────────────────

  new ResizeObserver(() => {{
    chart.applyOptions({{ width: container.clientWidth, height: container.clientHeight }});
    updateZoneBands(container, candleSeries);
  }}).observe(container);

  // Legend
  const legend = document.getElementById(`legend-${{symbol}}`);
  legend.innerHTML = [
    {{ color: '#22c55e', label: 'Nến tăng' }},
    {{ color: '#ef4444', label: 'Nến giảm' }},
    {{ color: '#16a34a', label: 'Buy zone' }},
    {{ color: '#dc2626', label: 'Sell zone' }},
    {{ color: '#22c55e', label: 'Hỗ trợ' }},
    {{ color: '#f97316', label: 'Kháng cự' }},
  ].map(item => `<div class="legend-item">
    <div class="legend-dot" style="background:${{item.color}}"></div>
    <span>${{item.label}}</span>
  </div>`).join('');
}}

async function loadChart(symbol, tf) {{
  const container = document.getElementById(`chart-${{symbol}}`);
  container.innerHTML = '<div class="loading">Đang tải...</div>';
  try {{
    const chartData = await fetchChartData(symbol, tf, 300);
    buildChart(symbol, chartData, ALL_SIGNALS[symbol] || [], tf);
  }} catch (err) {{
    container.innerHTML = `<div class="loading">Lỗi: ${{err.message}}</div>`;
  }}
}}

// Nút chọn timeframe
document.querySelectorAll('.tf-btn').forEach(btn => {{
  btn.addEventListener('click', async () => {{
    const sym = btn.dataset.sym;
    const tf  = btn.dataset.tf;
    // Update active state
    document.querySelectorAll(`#tf-${{sym}} .tf-btn`).forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentTf[sym] = tf;
    await loadChart(sym, tf);
  }});
}});

function buildTable(allSignals) {{
  const tbody = document.getElementById('signal-tbody');
  const rows = [];
  for (const sym of SYMBOLS) {{
    for (const sig of (allSignals[sym] || [])) rows.push({{ ...sig, symbol: sym }});
  }}
  rows.sort((a, b) => b.time - a.time);

  if (rows.length === 0) {{
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#475569;padding:24px">Chưa có tín hiệu nào</td></tr>';
    return;
  }}

  tbody.innerHTML = rows.map(r => {{
    const color   = ACTION_COLOR[r.action] || '#94a3b8';
    const label   = ACTION_LABEL[r.action] || r.action;
    const score   = (r.buy_score || r.sell_score) ? `${{r.buy_score}} / ${{r.sell_score}}` : '—';
    return `<tr>
      <td style="white-space:nowrap">${{formatTime(r.time)}}</td>
      <td style="font-weight:600;color:#f1f5f9">${{r.symbol}}</td>
      <td><span class="badge" style="background:${{color}}22;color:${{color}}">${{label}}</span></td>
      <td>${{CONF_LABEL[r.confidence] || r.confidence || '—'}}</td>
      <td>${{score}}</td>
      <td style="font-weight:500">${{formatPrice(r.price)}}</td>
      <td style="color:#22c55e">${{formatPrice(r.support)}}</td>
      <td style="color:#f97316">${{formatPrice(r.resistance)}}</td>
    </tr>`;
  }}).join('');
}}

async function init() {{
  buildTable(ALL_SIGNALS);
  await Promise.all(SYMBOLS.map(sym => loadChart(sym, currentTf[sym])));
}}

init();
</script>
</body>
</html>"""
