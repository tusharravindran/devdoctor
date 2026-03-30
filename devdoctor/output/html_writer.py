"""HTML output writer with in-place background updates.

The browser opens a stable HTML shell once. Live events are written to a small
sidecar JS file that the shell polls every 2 seconds, so new logs land in the
report without reloading the page, switching tabs, or moving the viewport.
"""

import json
import os
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..utils import color

# ── Tab definitions ────────────────────────────────────────────────────────────
# (id, label, types-list, count-colour)
# types=None → show all events.
_TABS: List[Tuple[str, str, Optional[List[str]], str]] = [
    ("all",      "All",      None,
     "#8b949e"),
    ("errors",   "Errors",   ["error", "exception", "panic", "oom", "connection", "concurrency",
                               "unhandled", "stackoverflow", "traceback"],
     "#ff7b72"),
    ("latency",  "Latency",  ["latency", "latency_http", "latency_gin", "db_query"],
     "#ffd700"),
    ("queries",  "Queries",  ["query", "db_query", "eager_load"],
     "#79c0ff"),
    ("warnings", "Warnings", ["deprecation", "warning", "eager_load", "timeout"],
     "#f97316"),
]

# ── Per-type visual config ─────────────────────────────────────────────────────
_TYPE_META: Dict[str, Dict[str, str]] = {
    # ── Errors / crashes
    "error":        {"bar": "#ff5f5f", "badge_bg": "#c0392b", "badge_fg": "#fff",    "label": "ERROR"},
    "exception":    {"bar": "#fb7185", "badge_bg": "#4c0519", "badge_fg": "#fecdd3", "label": "EXCEPTION"},
    "panic":        {"bar": "#ff3366", "badge_bg": "#4a0015", "badge_fg": "#ffb3c6", "label": "PANIC"},
    "oom":          {"bar": "#e11d48", "badge_bg": "#4c0519", "badge_fg": "#fecdd3", "label": "OOM"},
    "connection":   {"bar": "#f43f5e", "badge_bg": "#4c0519", "badge_fg": "#fecdd3", "label": "CONN ERR"},
    "concurrency":  {"bar": "#c084fc", "badge_bg": "#3b0764", "badge_fg": "#e9d5ff", "label": "RACE"},
    "unhandled":    {"bar": "#fb7185", "badge_bg": "#4c0519", "badge_fg": "#fecdd3", "label": "UNHANDLED"},
    "stackoverflow":{"bar": "#f87171", "badge_bg": "#450a0a", "badge_fg": "#fecaca", "label": "STACK OVF"},
    "traceback":    {"bar": "#ff7b72", "badge_bg": "#c0392b", "badge_fg": "#fff",    "label": "TRACEBACK"},
    # ── Latency
    "latency":      {"bar": "#ffd700", "badge_bg": "#7d6608", "badge_fg": "#ffe",    "label": "LATENCY"},
    "latency_http": {"bar": "#ffd700", "badge_bg": "#5a4a00", "badge_fg": "#ffe",    "label": "HTTP"},
    "latency_gin":  {"bar": "#ffd700", "badge_bg": "#5a4a00", "badge_fg": "#ffe",    "label": "GIN"},
    # ── Queries
    "db_query":     {"bar": "#22d3ee", "badge_bg": "#0e4f5c", "badge_fg": "#a5f3fc", "label": "DB"},
    "query":        {"bar": "#5fafff", "badge_bg": "#1a5276", "badge_fg": "#fff",    "label": "QUERY"},
    # ── Warnings
    "timeout":      {"bar": "#fb923c", "badge_bg": "#431407", "badge_fg": "#fed7aa", "label": "TIMEOUT"},
    "eager_load":   {"bar": "#a78bfa", "badge_bg": "#3b1f6e", "badge_fg": "#ddd6fe", "label": "N+1"},
    "deprecation":  {"bar": "#f97316", "badge_bg": "#431407", "badge_fg": "#fed7aa", "label": "DEPRECATED"},
    "warning":      {"bar": "#facc15", "badge_bg": "#3f3000", "badge_fg": "#fef08a", "label": "WARNING"},
    # ── Catch-all
    "log":          {"bar": "#3d4450", "badge_bg": "#2d333b", "badge_fg": "#8b949e", "label": "LOG"},
}
_DEFAULT_META = _TYPE_META["log"]

_FLUSH_INTERVAL = 1.0


def _esc(s: Optional[str]) -> str:
    if not s:
        return ""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def _duration_color(duration_str: Optional[str]) -> str:
    """Return a CSS color for a duration value based on slowness thresholds."""
    try:
        ms = float(duration_str or "")
        if ms > 500:
            return "#ff7b72"
        if ms > 200:
            return "#ffd700"
        return "#3fb950"
    except (TypeError, ValueError):
        return "#c9d1d9"


class HtmlWriter:
    """Writes a live-updating HTML report without reloading the page."""

    def __init__(self, output_dir: Path, project_id: str, open_browser: bool = False):
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._html_path: Path = output_dir / f"output-{ts}.html"
        self._data_path: Path = output_dir / f"output-{ts}.js"
        self._project_id = project_id
        self._session_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._events: List[Dict[str, Any]] = []
        self._last_flush: float = 0.0

        self._write_shell()
        self._write_data(final=False)

        print(color.success(f"HTML output → {self._html_path}"), flush=True)
        if open_browser:
            webbrowser.open(self._html_path.as_uri(), autoraise=False)

    def add_event(self, event: Dict[str, Any]) -> None:
        enriched = dict(event)
        enriched["_ts"] = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._events.append(enriched)
        if time.monotonic() - self._last_flush >= _FLUSH_INTERVAL:
            self._write_data(final=False)

    def close(self) -> None:
        self._write_data(final=True)

    def _atomic_write(self, path: Path, content: str) -> None:
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)

    def _tab_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for tab_id, _, types, _ in _TABS:
            if types is None:
                counts[tab_id] = len(self._events)
            else:
                counts[tab_id] = sum(1 for event in self._events if event.get("type") in types)
        return counts

    def _write_data(self, final: bool) -> None:
        self._last_flush = time.monotonic()
        payload = {
            "rows": self._render_rows(),
            "counts": self._tab_counts(),
            "total": len(self._events),
            "final": final,
        }
        self._atomic_write(
            self._data_path,
            f"window.__DD_PATCH__({json.dumps(payload, ensure_ascii=False)});",
        )

    def _write_shell(self) -> None:
        storage_ns = json.dumps(f"dd:{self._html_path}")
        data_file = json.dumps(self._data_path.name)
        tab_groups_js = json.dumps({
            tab_id: types
            for tab_id, _, types, _ in _TABS
        })

        tab_buttons = "\n      ".join(
            f'<button class="tab-btn{" active" if tab_id == "all" else ""}" '
            f'data-tab="{tab_id}" onclick="switchTab(\'{tab_id}\')">'
            f'{label}'
            f'<span class="tab-cnt" style="color:{cnt_color}">0</span>'
            f'</button>'
            for tab_id, label, _, cnt_color in _TABS
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>devdoctor — {_esc(self._project_id)}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0 }}
    body {{
      background: #0d1117;
      color: #c9d1d9;
      font-family: 'SF Mono', 'Fira Code', Consolas, 'Courier New', monospace;
      font-size: 13px;
      line-height: 1.5;
    }}

    .top-bar {{
      position: sticky; top: 0; z-index: 30;
      background: #161b22;
      border-bottom: 1px solid #30363d;
      padding: 9px 18px;
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    }}
    .app-name {{ font-size: 14px; font-weight: 700; color: #58a6ff; letter-spacing: .3px }}
    .status-pill {{
      display: inline-block; padding: 2px 8px; border-radius: 20px;
      font-size: 11px; font-weight: 700; letter-spacing: .4px;
      background: #2ea043; color: #000;
    }}
    .session-meta {{ color: #8b949e; font-size: 12px }}
    .session-meta b {{ color: #c9d1d9 }}
    .event-total {{ margin-left: auto; color: #8b949e; font-size: 12px }}

    .tab-bar {{
      position: sticky; top: 44px; z-index: 25;
      background: #161b22;
      border-bottom: 1px solid #30363d;
      padding: 0 14px;
      display: flex; gap: 2px;
    }}
    .tab-btn {{
      background: none; border: none; cursor: pointer;
      color: #8b949e; font-size: 12px; font-family: inherit;
      padding: 9px 14px; border-bottom: 2px solid transparent;
      display: flex; align-items: center; gap: 7px;
      transition: color .15s, border-color .15s;
      white-space: nowrap;
    }}
    .tab-btn:hover {{ color: #c9d1d9 }}
    .tab-btn.active {{ color: #c9d1d9; border-bottom-color: #58a6ff }}
    .tab-cnt {{
      font-size: 11px; font-weight: 700;
      background: #21262d; padding: 1px 6px; border-radius: 10px;
    }}

    table {{ width: 100%; border-collapse: collapse }}
    thead th {{
      position: sticky; top: 90px;
      background: #0d1117;
      border-bottom: 1px solid #30363d;
      color: #8b949e; font-weight: 600; font-size: 11px;
      text-transform: uppercase; letter-spacing: .5px;
      padding: 7px 14px; text-align: left;
    }}
    tbody tr {{ border-bottom: 1px solid #161b22 }}
    tbody tr:hover td {{ background: #1c2128 }}
    td {{ padding: 5px 14px; vertical-align: top }}

    tr.ev td:first-child {{ border-left: 3px solid transparent }}
    tr.ev-error        td:first-child {{ border-left-color: #ff5f5f }}
    tr.ev-exception    td:first-child {{ border-left-color: #fb7185 }}
    tr.ev-panic        td:first-child {{ border-left-color: #ff3366 }}
    tr.ev-oom          td:first-child {{ border-left-color: #e11d48 }}
    tr.ev-connection   td:first-child {{ border-left-color: #f43f5e }}
    tr.ev-concurrency  td:first-child {{ border-left-color: #c084fc }}
    tr.ev-unhandled    td:first-child {{ border-left-color: #fb7185 }}
    tr.ev-stackoverflow td:first-child {{ border-left-color: #f87171 }}
    tr.ev-traceback    td:first-child {{ border-left-color: #ff7b72 }}
    tr.ev-latency      td:first-child {{ border-left-color: #ffd700 }}
    tr.ev-latency_http td:first-child {{ border-left-color: #ffd700 }}
    tr.ev-latency_gin  td:first-child {{ border-left-color: #ffd700 }}
    tr.ev-db_query     td:first-child {{ border-left-color: #22d3ee }}
    tr.ev-query        td:first-child {{ border-left-color: #5fafff }}
    tr.ev-timeout      td:first-child {{ border-left-color: #fb923c }}
    tr.ev-eager_load   td:first-child {{ border-left-color: #a78bfa }}
    tr.ev-deprecation  td:first-child {{ border-left-color: #f97316 }}
    tr.ev-warning      td:first-child {{ border-left-color: #facc15 }}
    tr.ev-log          td:first-child {{ border-left-color: #30363d }}

    .c-ts    {{ color: #8b949e; white-space: nowrap; width: 76px }}
    .c-type  {{ white-space: nowrap; width: 110px }}
    .badge {{
      display: inline-block; padding: 1px 7px; border-radius: 4px;
      font-size: 11px; font-weight: 700; letter-spacing: .3px;
    }}
    .c-details {{ color: #e6edf3; width: 38% }}
    .d-msg    {{ color: #ff7b72 }}
    .d-key    {{ color: #79c0ff }}
    .d-sep    {{ color: #484f58; margin: 0 4px }}
    .d-dur    {{ font-weight: 700 }}

    .c-raw {{
      color: #484f58; cursor: pointer;
      max-width: 380px; overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap;
      user-select: none;
    }}
    .c-raw::after {{ content: ' ▶'; font-size: 10px; opacity: .4 }}
    .c-raw.expanded {{
      color: #8b949e; white-space: pre-wrap;
      overflow: visible; max-width: none;
    }}
    .c-raw.expanded::after {{ content: ' ▼'; opacity: .4 }}

    .empty-state td {{
      text-align: center; color: #484f58;
      padding: 60px 0; font-size: 14px; border: none;
    }}

    footer {{
      color: #484f58; font-size: 11px;
      padding: 12px 18px; border-top: 1px solid #21262d;
    }}
  </style>
</head>
<body>
  <div class="top-bar">
    <span class="app-name">devdoctor</span>
    <span class="status-pill" id="dd-status">LIVE</span>
    <span class="session-meta">
      project: <b>{_esc(self._project_id)}</b>
      &nbsp;&middot;&nbsp;
      session: <b>{self._session_ts}</b>
    </span>
    <span class="event-total" id="dd-total">0 events total</span>
  </div>

  <div class="tab-bar">
    {tab_buttons}
  </div>

  <table>
    <thead>
      <tr>
        <th class="c-ts">Time</th>
        <th class="c-type">Type</th>
        <th class="c-details">Details</th>
        <th>Raw log <span style="color:#3d4450;font-weight:400">(click to expand)</span></th>
      </tr>
    </thead>
    <tbody id="tbody">
      <tr id="empty-state" class="empty-state">
        <td colspan="4">Waiting for log events&hellip;</td>
      </tr>
    </tbody>
  </table>

  <footer id="dd-footer">
    {_esc(self._html_path.name)} &nbsp;&middot;&nbsp; updates in background every 2s
  </footer>

  <script>
    var STORAGE_NS = {storage_ns};
    var TABS = {tab_groups_js};
    var DATA_FILE = {data_file};
    var activeTab = sessionStorage.getItem(STORAGE_NS + ':tab') || 'all';
    var knownCount = 0;
    var pollTimer = null;

    function switchTab(id) {{
      activeTab = id;
      sessionStorage.setItem(STORAGE_NS + ':tab', id);
      document.querySelectorAll('.tab-btn').forEach(function(btn) {{
        btn.classList.toggle('active', btn.dataset.tab === id);
      }});

      var types = TABS[id];
      var shown = 0;
      document.querySelectorAll('tr.ev').forEach(function(row) {{
        var show = !types || types.indexOf(row.dataset.type) !== -1;
        row.style.display = show ? '' : 'none';
        if (show) shown++;
      }});

      var empty = document.getElementById('empty-state');
      if (empty) empty.style.display = shown === 0 ? '' : 'none';
    }}

    function updateCounts(counts) {{
      document.querySelectorAll('.tab-btn').forEach(function(btn) {{
        var cnt = btn.querySelector('.tab-cnt');
        if (cnt && counts[btn.dataset.tab] !== undefined) {{
          cnt.textContent = counts[btn.dataset.tab];
        }}
      }});
    }}

    function appendRows(rowsHtml, total) {{
      if (total <= knownCount) return;

      var tbody = document.getElementById('tbody');
      var types = TABS[activeTab];
      var tmp = document.createElement('table');
      tmp.innerHTML = '<tbody>' + rowsHtml + '</tbody>';
      var allRows = Array.from(tmp.querySelectorAll('tr.ev'));
      var newRows = allRows.slice(knownCount);

      if (knownCount === 0) {{
        tbody.innerHTML = '';
      }} else {{
        var existingEmpty = document.getElementById('empty-state');
        if (existingEmpty) existingEmpty.remove();
      }}

      newRows.forEach(function(row) {{
        if (types && types.indexOf(row.dataset.type) === -1) {{
          row.style.display = 'none';
        }}
        tbody.appendChild(row);
      }});

      var sentinel = document.createElement('tr');
      sentinel.id = 'empty-state';
      sentinel.className = 'empty-state';
      sentinel.style.display = 'none';
      sentinel.innerHTML = '<td colspan="4">No events match this filter</td>';
      tbody.appendChild(sentinel);

      knownCount = total;
      switchTab(activeTab);
    }}

    window.__DD_PATCH__ = function(data) {{
      appendRows(data.rows, data.total);
      updateCounts(data.counts || {{}});

      var totalEl = document.getElementById('dd-total');
      if (totalEl) totalEl.textContent = data.total + ' events total';

      if (data.final) {{
        var pill = document.getElementById('dd-status');
        if (pill) {{
          pill.textContent = 'DONE';
          pill.style.background = '#8b949e';
        }}
        var footer = document.getElementById('dd-footer');
        if (footer) {{
          footer.innerHTML = '{_esc(self._html_path.name)} &nbsp;&middot;&nbsp; session ended';
        }}
        if (pollTimer) clearInterval(pollTimer);
      }}
    }};

    function loadData() {{
      var existing = document.getElementById('dd-data-script');
      if (existing) existing.remove();

      var script = document.createElement('script');
      script.id = 'dd-data-script';
      script.src = DATA_FILE + '?_=' + Date.now();
      document.head.appendChild(script);
    }}

    document.addEventListener('click', function(e) {{
      var cell = e.target.closest('td.c-raw');
      if (!cell) return;

      var expanded = cell.classList.toggle('expanded');
      cell.textContent = expanded ? (cell.dataset.full || '') : (cell.dataset.short || '');
    }});

    window.addEventListener('DOMContentLoaded', function() {{
      switchTab(activeTab);
      loadData();
      pollTimer = setInterval(loadData, 2000);
    }});
  </script>
</body>
</html>"""

        self._atomic_write(self._html_path, html)

    def _render_rows(self) -> str:
        if not self._events:
            return ""

        parts: List[str] = []
        for ev in self._events:
            ev_type = ev.get("type", "log")
            meta = _TYPE_META.get(ev_type, _DEFAULT_META)

            ts = _esc(ev.get("_ts", ""))
            badge = (
                f'<span class="badge" '
                f'style="background:{meta["badge_bg"]};color:{meta["badge_fg"]}">'
                f'{meta["label"]}</span>'
            )

            parts_d: List[str] = []

            if ev.get("message"):
                parts_d.append(f'<span class="d-msg">{_esc(str(ev["message"])[:120])}</span>')

            if ev.get("duration") is not None:
                dur_str = str(ev["duration"])
                dur_col = _duration_color(dur_str)
                try:
                    dur_display = f"{float(dur_str):.1f}".rstrip("0").rstrip(".") + "ms"
                except ValueError:
                    dur_display = dur_str + "ms"
                parts_d.append(
                    f'<span class="d-key">duration</span>'
                    f'<span class="d-sep">=</span>'
                    f'<span class="d-dur" style="color:{dur_col}">{_esc(dur_display)}</span>'
                )

            if ev.get("table"):
                parts_d.append(
                    f'<span class="d-key">table</span>'
                    f'<span class="d-sep">=</span>'
                    f'<span style="color:#c9d1d9">{_esc(ev["table"])}</span>'
                )

            details = (
                ' &nbsp; '.join(parts_d)
                if parts_d
                else '<span style="color:#484f58">—</span>'
            )

            raw_full = _esc(ev.get("raw", ""))
            raw_short = _esc((ev.get("raw") or "")[:120])

            parts.append(
                f'<tr class="ev ev-{ev_type}" data-type="{ev_type}">'
                f'<td class="c-ts">{ts}</td>'
                f'<td class="c-type">{badge}</td>'
                f'<td class="c-details">{details}</td>'
                f'<td class="c-raw" data-full="{raw_full}" data-short="{raw_short}">{raw_short}</td>'
                f'</tr>'
            )

        return "\n".join(parts)
