"""Read-only paper dashboard server. Serves state JSON and a static page."""
from __future__ import annotations

import errno
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from dashboard import DashboardState

PAGE = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Agent Trading — Paper</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; font: 14px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; background: #0d1117; color: #c9d1d9; }
  header { padding: 16px 20px; border-bottom: 1px solid #21262d; display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
  h1 { font-size: 16px; margin: 0; color: #58a6ff; }
  .badge { padding: 2px 8px; border-radius: 999px; font-size: 12px; border: 1px solid #30363d; }
  .live { color: #f85149; border-color: #f85149; }
  .paper { color: #3fb950; border-color: #3fb950; }
  main { padding: 20px; max-width: 1100px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 18px; }
  .card { background: #161b22; border: 1px solid #21262d; border-radius: 6px; padding: 10px 12px; }
  .card .k { color: #8b949e; font-size: 11px; text-transform: uppercase; letter-spacing: .05em; }
  .card .v { font-size: 18px; color: #e6edf3; margin-top: 4px; word-break: break-all; }
  h2 { font-size: 13px; color: #8b949e; text-transform: uppercase; letter-spacing: .05em; margin: 22px 0 8px; }
  .gain { color: #3fb950; } .loss { color: #f85149; }
  #chart { width: 100%; height: 220px; background: #161b22; border: 1px solid #21262d; border-radius: 6px; display: block; }
  .chartwrap { position: relative; }
  .chartnote { color: #6e7681; font-size: 12px; margin-top: 6px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #21262d; vertical-align: top; }
  th { color: #8b949e; font-weight: 500; }
  .hold { color: #d29922; } .buy { color: #3fb950; } .invalid { color: #f85149; }
  .empty { color: #6e7681; font-style: italic; }
  .foot { margin-top: 20px; color: #6e7681; font-size: 12px; }
  code { color: #79c0ff; }
</style>
</head>
<body>
<header>
  <h1>AI Agent Trading</h1>
  <span class="badge paper">PAPER</span>
  <span class="badge live">LIVE TRADING DISABLED</span>
  <span class="badge" id="model">model: -</span>
  <span class="badge" id="status">status: -</span>
</header>
<main>
  <div class="cards" id="cards"></div>
  <h2>Equity and P/L</h2>
  <div class="chartwrap"><svg id="chart" viewBox="0 0 1000 220" preserveAspectRatio="none"></svg></div>
  <p class="chartnote" id="chartnote"></p>
  <h2>Position</h2>
  <div id="positions"></div>
  <h2>Cycle log</h2>
  <div id="history"></div>
  <p class="foot">Read-only view. Order placement happens in the agent loop after schema validation and the risk gate, never from this page.</p>
</main>
<script>
const fmt = (v, d=2) => (v === null || v === undefined) ? '-' : Number(v).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d});

// Equity curve. Initial capital is always the baseline line, so the chart shows
// profit above it and loss below it rather than an arbitrary scale.
function drawChart(s) {
  const svg = document.getElementById('chart');
  const note = document.getElementById('chartnote');
  const pts = (s.equity_curve || []).map(p => p.equity).filter(v => typeof v === 'number');
  const cap = Number(s.initial_capital || 1000);
  if (pts.length < 2) {
    svg.innerHTML = '<text x="500" y="115" fill="#6e7681" text-anchor="middle" font-size="13">collecting equity points...</text>';
    note.textContent = 'The curve starts once the agent has completed two cycles.';
    return;
  }
  const all = pts.concat([cap]);
  let lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
  if (hi === lo) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.15; lo -= pad; hi += pad;
  const W = 1000, H = 220, top = 10, bottom = 20;
  const x = i => (i / (pts.length - 1)) * W;
  const y = v => top + (1 - (v - lo) / (hi - lo)) * (H - top - bottom);
  const baseY = y(cap);
  const last = pts[pts.length - 1];
  const up = last >= cap;
  const color = up ? '#3fb950' : '#f85149';
  const line = pts.map((v, i) => (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1)).join(' ');
  const area = line + ' L' + W + ' ' + baseY.toFixed(1) + ' L0 ' + baseY.toFixed(1) + ' Z';
  const grid = [0, .5, 1].map(f => {
    const gy = top + f * (H - top - bottom);
    return '<line x1="0" y1="' + gy.toFixed(1) + '" x2="' + W + '" y2="' + gy.toFixed(1) + '" stroke="#21262d" stroke-width="1"/>';
  }).join('');
  svg.innerHTML = grid +
    '<rect x="0" y="' + top + '" width="' + W + '" height="' + Math.max(0, baseY - top).toFixed(1) + '" fill="' + color + '" opacity="0.07"/>' +
    '<line x1="0" y1="' + baseY.toFixed(1) + '" x2="' + W + '" y2="' + baseY.toFixed(1) + '" stroke="#6e7681" stroke-width="1" stroke-dasharray="4 4"/>' +
    '<path d="' + area + '" fill="' + color + '" opacity="0.12"/>' +
    '<path d="' + line + '" fill="none" stroke="' + color + '" stroke-width="2" stroke-linejoin="round"/>' +
    '<circle cx="' + W + '" cy="' + y(last).toFixed(1) + '" r="4" fill="' + color + '"/>' +
    '<text x="8" y="16" fill="#8b949e" font-size="11">hi ' + fmt(hi) + '</text>' +
    '<text x="8" y="212" fill="#8b949e" font-size="11">lo ' + fmt(lo) + '</text>' +
    '<text x="992" y="' + Math.max(14, baseY - 6).toFixed(1) + '" fill="#8b949e" font-size="11" text-anchor="end">start ' + fmt(cap) + '</text>';
  note.textContent = pts.length + ' points. Dashed line = starting capital ' + fmt(cap) + ' USDT. ' +
    'Latest ' + fmt(last, 2) + ' USDT (' + (up ? '+' : '') + fmt(last - cap) + ' USDT).';
}

function render(s) {
  document.getElementById('model').textContent = 'model: ' + (s.model || '-');
  document.getElementById('status').textContent = 'status: ' + (s.status || '-');
  const pnl = (s.pnl_usdt === null || s.pnl_usdt === undefined) ? null : Number(s.pnl_usdt);
  const cls = pnl === null ? '' : (pnl >= 0 ? 'gain' : 'loss');
  const cards = [
    ['equity (USDT)', '<span class="' + cls + '">' + fmt(s.equity, 2) + '</span>'],
    ['P/L (USDT)', '<span class="' + cls + '">' + (pnl === null ? '-' : (pnl >= 0 ? '+' : '') + fmt(pnl, 2)) + '</span>'],
    ['return', '<span class="' + cls + '">' + (s.return_pct === null || s.return_pct === undefined ? '-' : (s.return_pct >= 0 ? '+' : '') + fmt(s.return_pct, 2) + '%') + '</span>'],
    ['max drawdown', fmt(s.max_drawdown_pct, 2) + '%'],
    ['cash (USDT)', fmt(s.cash, 2)],
    ['mark price', fmt(s.mark_price, 1)],
    ['exposure / cap', fmt(s.mark_exposure, 2) + ' / ' + fmt(s.max_exposure, 0)],
    ['cycles', s.cycles],
    ['executed', s.executed],
    ['invalid', s.invalid],
  ];
  document.getElementById('cards').innerHTML = cards.map(([k, v]) =>
    '<div class="card"><div class="k">' + k + '</div><div class="v">' + v + '</div></div>').join('');
  drawChart(s);
  const p = (s.positions || []);
  document.getElementById('positions').innerHTML = p.length ? '<table><tr><th>sym</th><th>qty</th><th>entry</th><th>ledger px</th><th>pnl</th></tr>' +
    p.map(x => '<tr><td>' + x.symbol + '</td><td>' + x.quantity + '</td><td>' + fmt(x.entry_price,1) + '</td><td>' + fmt(x.ledger_current_price,1) + '</td><td>' + fmt(x.ledger_pnl,4) + '</td></tr>').join('') + '</table>'
    : '<p class="empty">no open position</p>';
  const h = (s.history || []).slice().reverse();
  document.getElementById('history').innerHTML = h.length ? '<table><tr><th>ts</th><th>close</th><th>baseline</th><th>agent</th><th>conf</th><th>validation</th><th>relation</th><th>risk</th><th>exec</th><th>reasons</th></tr>' +
    h.map(c => '<tr><td>' + new Date(c.candle_timestamp).toISOString().slice(0,16).replace('T',' ') + '</td><td>' + fmt(c.close,1) + '</td><td>' + c.baseline_signal +
      '</td><td class="' + c.agent_action + '">' + c.agent_action + '</td><td>' + fmt(c.agent_confidence,2) + '</td><td class="' + (c.validation === 'valid' ? '' : 'invalid') + '">' + c.validation +
      '</td><td>' + c.relation + '</td><td>' + (c.risk_reason || '-') + '</td><td>' + (c.executed ? 'yes' : 'no') + '</td><td>' + ((c.agent_reason_codes || []).join(', ') || '-') +
      ((c.agent_invalid_conditions || []).length ? ' ⚠ ' + c.agent_invalid_conditions.join(', ') : '') + '</td></tr>').join('') + '</table>'
    : '<p class="empty">waiting for first cycle</p>';
}
async function tick() { try { render(await (await fetch('/api/state')).json()); } catch (e) {} }
tick(); setInterval(tick, 5000);
</script>
</body>
</html>
"""


def make_handler(state_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence access log
            return

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/api/state"):
                state = DashboardState(state_path).data
                self._send(200, json.dumps(state, sort_keys=True).encode(), "application/json")
                return
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
                return
            self._send(404, b"not found", "text/plain")

    return Handler


def serve(state_path: Path, host: str = "127.0.0.1", port: int = 8788) -> None:
    server = HTTPServer((host, port), make_handler(Path(state_path)))
    server.serve_forever()


def serve_with_reuse(state_path: Path, host: str = "127.0.0.1", port: int = 8788,
                     attempts: int = 10, delay: float = 1.0) -> None:
    """Serve on `port`, tolerating a socket still held by a dying process.

    A supervisor restart can land in the window where the old listener has not
    fully released the port. Without this the dashboard thread dies on a
    silent OSError and the whole run looks broken while the agent still works.
    """
    last_error: OSError | None = None
    for _ in range(attempts):
        try:
            serve(state_path, host, port)
            return
        except OSError as exc:
            if exc.errno not in (errno.EADDRINUSE,):
                raise
            last_error = exc
            time.sleep(delay)
    raise RuntimeError(f"port {port} still busy after {attempts} attempts: {last_error}")
