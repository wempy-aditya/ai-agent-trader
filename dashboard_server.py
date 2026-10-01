"""Read-only paper dashboard server. Serves state JSON and a static page."""
from __future__ import annotations

import json
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
  <h2>Position</h2>
  <div id="positions"></div>
  <h2>Cycle log</h2>
  <div id="history"></div>
  <p class="foot">Read-only view. Order placement happens in the agent loop after schema validation and the risk gate, never from this page.</p>
</main>
<script>
const fmt = (v, d=2) => (v === null || v === undefined) ? '-' : Number(v).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d});
function render(s) {
  document.getElementById('model').textContent = 'model: ' + (s.model || '-');
  document.getElementById('status').textContent = 'status: ' + (s.status || '-');
  const cards = [
    ['cash (USDT)', fmt(s.cash, 4)],
    ['mark price', fmt(s.mark_price, 1)],
    ['exposure / cap', fmt(s.mark_exposure, 2) + ' / ' + fmt(s.max_exposure, 0)],
    ['cycles', s.cycles],
    ['executed', s.executed],
    ['invalid', s.invalid],
  ];
  document.getElementById('cards').innerHTML = cards.map(([k, v]) =>
    '<div class="card"><div class="k">' + k + '</div><div class="v">' + v + '</div></div>').join('');
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
