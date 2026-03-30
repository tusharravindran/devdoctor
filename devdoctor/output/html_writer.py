"""HTML output writer with in-place background updates.

The browser opens a stable HTML shell once. Live events are written to a small
sidecar JS file that the shell polls every 2 seconds, so new logs land in the
report without reloading the page, switching tabs, or moving the viewport.
"""

from __future__ import annotations

import json
import os
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils import color

_TABS: List[Dict[str, Any]] = [
    {"id": "all", "label": "All", "kind": "events", "types": None, "count_color": "#8b949e"},
    {
        "id": "errors",
        "label": "Errors",
        "kind": "events",
        "types": [
            "error",
            "exception",
            "panic",
            "oom",
            "connection",
            "concurrency",
            "unhandled",
            "stackoverflow",
            "traceback",
        ],
        "count_color": "#ff7b72",
    },
    {
        "id": "latency",
        "label": "Latency",
        "kind": "events",
        "types": ["latency", "latency_http", "latency_gin", "db_query"],
        "count_color": "#ffd700",
    },
    {
        "id": "queries",
        "label": "Queries",
        "kind": "events",
        "types": ["query", "db_query", "eager_load"],
        "count_color": "#79c0ff",
    },
    {
        "id": "warnings",
        "label": "Warnings",
        "kind": "issues",
        "issue_view": "warnings",
        "count_color": "#f97316",
    },
    {
        "id": "suggestions",
        "label": "Suggestions",
        "kind": "issues",
        "issue_view": "suggestions",
        "count_color": "#2ea043",
    },
]

_TYPE_META: Dict[str, Dict[str, str]] = {
    "error": {"bar": "#ff5f5f", "badge_bg": "#c0392b", "badge_fg": "#fff", "label": "ERROR"},
    "exception": {"bar": "#fb7185", "badge_bg": "#4c0519", "badge_fg": "#fecdd3", "label": "EXCEPTION"},
    "panic": {"bar": "#ff3366", "badge_bg": "#4a0015", "badge_fg": "#ffb3c6", "label": "PANIC"},
    "oom": {"bar": "#e11d48", "badge_bg": "#4c0519", "badge_fg": "#fecdd3", "label": "OOM"},
    "connection": {"bar": "#f43f5e", "badge_bg": "#4c0519", "badge_fg": "#fecdd3", "label": "CONN ERR"},
    "concurrency": {"bar": "#c084fc", "badge_bg": "#3b0764", "badge_fg": "#e9d5ff", "label": "RACE"},
    "unhandled": {"bar": "#fb7185", "badge_bg": "#4c0519", "badge_fg": "#fecdd3", "label": "UNHANDLED"},
    "stackoverflow": {"bar": "#f87171", "badge_bg": "#450a0a", "badge_fg": "#fecaca", "label": "STACK OVF"},
    "traceback": {"bar": "#ff7b72", "badge_bg": "#c0392b", "badge_fg": "#fff", "label": "TRACEBACK"},
    "latency": {"bar": "#ffd700", "badge_bg": "#7d6608", "badge_fg": "#ffe", "label": "LATENCY"},
    "latency_http": {"bar": "#ffd700", "badge_bg": "#5a4a00", "badge_fg": "#ffe", "label": "HTTP"},
    "latency_gin": {"bar": "#ffd700", "badge_bg": "#5a4a00", "badge_fg": "#ffe", "label": "GIN"},
    "db_query": {"bar": "#22d3ee", "badge_bg": "#0e4f5c", "badge_fg": "#a5f3fc", "label": "DB"},
    "query": {"bar": "#5fafff", "badge_bg": "#1a5276", "badge_fg": "#fff", "label": "QUERY"},
    "timeout": {"bar": "#fb923c", "badge_bg": "#431407", "badge_fg": "#fed7aa", "label": "TIMEOUT"},
    "eager_load": {"bar": "#a78bfa", "badge_bg": "#3b1f6e", "badge_fg": "#ddd6fe", "label": "N+1"},
    "deprecation": {"bar": "#f97316", "badge_bg": "#431407", "badge_fg": "#fed7aa", "label": "DEPRECATED"},
    "warning": {"bar": "#facc15", "badge_bg": "#3f3000", "badge_fg": "#fef08a", "label": "WARNING"},
    "log": {"bar": "#3d4450", "badge_bg": "#2d333b", "badge_fg": "#8b949e", "label": "LOG"},
}

_STATUS_META: Dict[str, Dict[str, str]] = {
    "detected": {"bg": "#1f2937", "fg": "#cbd5e1", "label": "DETECTED"},
    "suggested": {"bg": "#052e16", "fg": "#86efac", "label": "SUGGESTED"},
    "cleared": {"bg": "#0f172a", "fg": "#67e8f9", "label": "CLEARED"},
    "ignored": {"bg": "#2d333b", "fg": "#8b949e", "label": "IGNORED"},
}

_DEFAULT_META = _TYPE_META["log"]
_DEFAULT_STATUS_META = _STATUS_META["detected"]
_FLUSH_INTERVAL = 1.0


def _esc(value: Optional[str]) -> str:
    if not value:
        return ""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


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

    def __init__(
        self,
        output_dir: Path,
        project_id: str,
        issue_tracker,
        open_browser: bool = False,
    ) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._html_path: Path = output_dir / f"output-{ts}.html"
        self._data_path: Path = output_dir / f"output-{ts}.js"
        self._project_id = project_id
        self._issue_tracker = issue_tracker
        self._session_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._events: List[Dict[str, Any]] = []
        self._last_flush: float = 0.0
        self._closed = False

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
        if self._closed:
            return
        self._closed = True
        self._write_data(final=True)

    def _atomic_write(self, path: Path, content: str) -> None:
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)

    def _tab_counts(self, final: bool) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for tab in _TABS:
            if tab["kind"] == "issues":
                counts[tab["id"]] = self._issue_tracker.tab_counts(final=final)[tab["id"]]
                continue

            tab_types = tab["types"]
            if tab_types is None:
                counts[tab["id"]] = len(self._events)
            else:
                counts[tab["id"]] = sum(
                    1 for event in self._events if event.get("type") in tab_types
                )
        return counts

    def _write_data(self, final: bool) -> None:
        self._last_flush = time.monotonic()
        payload = {
            "rows": self._render_rows(),
            "counts": self._tab_counts(final=final),
            "total": len(self._events),
            "final": final,
            "issue_views": {
                "warnings": self._render_warning_cards(),
                "suggestions": self._render_suggestion_cards(final=final),
            },
        }
        self._atomic_write(
            self._data_path,
            f"window.__DD_PATCH__({json.dumps(payload, ensure_ascii=False)});",
        )

    def _write_shell(self) -> None:
        storage_ns = json.dumps(f"dd:{self._html_path}")
        data_file = json.dumps(self._data_path.name)
        tab_meta_js = json.dumps(
            {
                tab["id"]: {
                    "kind": tab["kind"],
                    "types": tab.get("types"),
                    "issue_view": tab.get("issue_view"),
                }
                for tab in _TABS
            }
        )

        tab_buttons = "\n      ".join(
            f'<button class="tab-btn{" active" if tab["id"] == "all" else ""}" '
            f'data-tab="{tab["id"]}" onclick="switchTab(\'{tab["id"]}\')">'
            f'{tab["label"]}'
            f'<span class="tab-cnt" style="color:{tab["count_color"]}">0</span>'
            f"</button>"
            for tab in _TABS
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
      overflow-x: auto;
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

    #event-view {{ display: block }}
    #issue-view {{ display: none; padding: 18px; }}

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
    tr.ev-error td:first-child {{ border-left-color: #ff5f5f }}
    tr.ev-exception td:first-child {{ border-left-color: #fb7185 }}
    tr.ev-panic td:first-child {{ border-left-color: #ff3366 }}
    tr.ev-oom td:first-child {{ border-left-color: #e11d48 }}
    tr.ev-connection td:first-child {{ border-left-color: #f43f5e }}
    tr.ev-concurrency td:first-child {{ border-left-color: #c084fc }}
    tr.ev-unhandled td:first-child {{ border-left-color: #fb7185 }}
    tr.ev-stackoverflow td:first-child {{ border-left-color: #f87171 }}
    tr.ev-traceback td:first-child {{ border-left-color: #ff7b72 }}
    tr.ev-latency td:first-child {{ border-left-color: #ffd700 }}
    tr.ev-latency_http td:first-child {{ border-left-color: #ffd700 }}
    tr.ev-latency_gin td:first-child {{ border-left-color: #ffd700 }}
    tr.ev-db_query td:first-child {{ border-left-color: #22d3ee }}
    tr.ev-query td:first-child {{ border-left-color: #5fafff }}
    tr.ev-timeout td:first-child {{ border-left-color: #fb923c }}
    tr.ev-eager_load td:first-child {{ border-left-color: #a78bfa }}
    tr.ev-deprecation td:first-child {{ border-left-color: #f97316 }}
    tr.ev-warning td:first-child {{ border-left-color: #facc15 }}
    tr.ev-log td:first-child {{ border-left-color: #30363d }}

    .c-ts {{ color: #8b949e; white-space: nowrap; width: 76px }}
    .c-type {{ white-space: nowrap; width: 110px }}
    .badge {{
      display: inline-block; padding: 1px 7px; border-radius: 4px;
      font-size: 11px; font-weight: 700; letter-spacing: .3px;
    }}
    .c-details {{ color: #e6edf3; width: 38% }}
    .d-msg {{ color: #ff7b72 }}
    .d-key {{ color: #79c0ff }}
    .d-sep {{ color: #484f58; margin: 0 4px }}
    .d-dur {{ font-weight: 700 }}

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

    .issue-section + .issue-section {{ margin-top: 20px }}
    .issue-section-title {{
      color: #e6edf3;
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 6px;
    }}
    .issue-section-copy {{
      color: #8b949e;
      font-size: 12px;
      margin-bottom: 12px;
    }}
    .issue-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 12px;
    }}
    .issue-card {{
      background: #11161d;
      border: 1px solid #30363d;
      border-left: 4px solid #30363d;
      border-radius: 10px;
      padding: 14px;
      box-shadow: 0 0 0 1px rgba(13, 17, 23, 0.08);
    }}
    .issue-card.warning {{ border-left-color: #f97316 }}
    .issue-card.suggested {{ border-left-color: #2ea043 }}
    .issue-card.cleared {{ border-left-color: #67e8f9 }}
    .issue-card.detected {{ border-left-color: #8b949e }}
    .issue-head {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
      margin-bottom: 8px;
    }}
    .issue-title {{
      color: #f0f6fc;
      font-size: 14px;
      font-weight: 700;
      line-height: 1.4;
    }}
    .issue-badges {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      justify-content: flex-end;
      min-width: 120px;
    }}
    .issue-chip {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .3px;
      background: #21262d;
      color: #c9d1d9;
    }}
    .issue-chip.type {{ background: #1f2937; color: #bfdbfe }}
    .issue-chip.count {{ background: #21262d; color: #f0f6fc }}
    .issue-body {{
      color: #c9d1d9;
      display: grid;
      gap: 8px;
    }}
    .issue-label {{ color: #8b949e; font-size: 11px; text-transform: uppercase; letter-spacing: .5px }}
    .issue-copy {{ color: #c9d1d9 }}
    .issue-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      color: #8b949e;
      font-size: 11px;
    }}
    .issue-example {{
      background: #0d1117;
      border: 1px solid #21262d;
      border-radius: 8px;
      color: #8b949e;
      font-size: 12px;
      padding: 10px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .issue-empty {{
      color: #6e7681;
      text-align: center;
      padding: 60px 12px;
      border: 1px dashed #30363d;
      border-radius: 12px;
      background: #11161d;
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

  <div id="event-view">
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
  </div>

  <div id="issue-view"></div>

  <footer id="dd-footer">
    {_esc(self._html_path.name)} &nbsp;&middot;&nbsp; updates in background every 2s
  </footer>

  <script>
    var STORAGE_NS = {storage_ns};
    var TAB_META = {tab_meta_js};
    var DATA_FILE = {data_file};
    var activeTab = sessionStorage.getItem(STORAGE_NS + ':tab') || 'all';
    var knownCount = 0;
    var pollTimer = null;
    var latestIssueViews = {{ warnings: '', suggestions: '' }};

    function renderActiveView() {{
      var tab = TAB_META[activeTab] || TAB_META.all;
      var eventView = document.getElementById('event-view');
      var issueView = document.getElementById('issue-view');

      if (tab.kind === 'issues') {{
        eventView.style.display = 'none';
        issueView.style.display = 'block';
        issueView.innerHTML = latestIssueViews[tab.issue_view] || '<div class="issue-empty">No grouped issues to show yet.</div>';
        return;
      }}

      eventView.style.display = 'block';
      issueView.style.display = 'none';

      var types = tab.types;
      var shown = 0;
      document.querySelectorAll('tr.ev').forEach(function(row) {{
        var show = !types || types.indexOf(row.dataset.type) !== -1;
        row.style.display = show ? '' : 'none';
        if (show) shown++;
      }});

      var empty = document.getElementById('empty-state');
      if (empty) empty.style.display = shown === 0 ? '' : 'none';
    }}

    function switchTab(id) {{
      activeTab = id;
      sessionStorage.setItem(STORAGE_NS + ':tab', id);
      document.querySelectorAll('.tab-btn').forEach(function(btn) {{
        btn.classList.toggle('active', btn.dataset.tab === id);
      }});
      renderActiveView();
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
        tbody.appendChild(row);
      }});

      var sentinel = document.createElement('tr');
      sentinel.id = 'empty-state';
      sentinel.className = 'empty-state';
      sentinel.style.display = 'none';
      sentinel.innerHTML = '<td colspan="4">No events match this filter</td>';
      tbody.appendChild(sentinel);

      knownCount = total;
    }}

    window.__DD_PATCH__ = function(data) {{
      appendRows(data.rows, data.total);
      latestIssueViews = data.issue_views || latestIssueViews;
      updateCounts(data.counts || {{}});
      renderActiveView();

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

            details_parts: List[str] = []
            if ev.get("message"):
                details_parts.append(
                    f'<span class="d-msg">{_esc(str(ev["message"])[:120])}</span>'
                )

            if ev.get("duration") is not None:
                dur_str = str(ev["duration"])
                dur_col = _duration_color(dur_str)
                try:
                    dur_display = f"{float(dur_str):.1f}".rstrip("0").rstrip(".") + "ms"
                except ValueError:
                    dur_display = dur_str + "ms"
                details_parts.append(
                    f'<span class="d-key">duration</span>'
                    f'<span class="d-sep">=</span>'
                    f'<span class="d-dur" style="color:{dur_col}">{_esc(dur_display)}</span>'
                )

            if ev.get("table"):
                details_parts.append(
                    f'<span class="d-key">table</span>'
                    f'<span class="d-sep">=</span>'
                    f'<span style="color:#c9d1d9">{_esc(str(ev["table"]))}</span>'
                )

            details = (
                " &nbsp; ".join(details_parts)
                if details_parts
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
                f"</tr>"
            )

        return "\n".join(parts)

    def _render_warning_cards(self) -> str:
        issues = self._issue_tracker.warning_issues()
        if not issues:
            return (
                '<div class="issue-empty">'
                "No warning fingerprints matched the current noise controls."
                "</div>"
            )

        cards = "\n".join(
            self._render_issue_card(issue, include_solution=False)
            for issue in issues
        )
        return (
            '<section class="issue-section">'
            '<div class="issue-section-title">Grouped warnings</div>'
            '<div class="issue-section-copy">'
            "Duplicates are collapsed by fingerprint. Each card shows the latest example and the number of times it repeated."
            "</div>"
            f'<div class="issue-grid">{cards}</div>'
            "</section>"
        )

    def _render_suggestion_cards(self, final: bool) -> str:
        active = [
            issue
            for issue in self._issue_tracker.suggestion_issues(final=False)
            if issue["status"] != "ignored"
        ]
        cleared = self._issue_tracker.cleared_issues() if final else []

        sections: List[str] = []
        if active:
            active_cards = "\n".join(
                self._render_issue_card(issue, include_solution=True)
                for issue in active
            )
            sections.append(
                '<section class="issue-section">'
                '<div class="issue-section-title">Active suggestions</div>'
                '<div class="issue-section-copy">'
                "Suggestions are attached to canonical issue fingerprints, so repeated warnings stay in one place while counts keep climbing."
                "</div>"
                f'<div class="issue-grid">{active_cards}</div>'
                "</section>"
            )

        if cleared:
            cleared_cards = "\n".join(
                self._render_issue_card(issue, include_solution=True)
                for issue in cleared
            )
            sections.append(
                '<section class="issue-section">'
                '<div class="issue-section-title">Cleared since previous run</div>'
                '<div class="issue-section-copy">'
                "These fingerprints existed in the last saved session and did not reappear in this one."
                "</div>"
                f'<div class="issue-grid">{cleared_cards}</div>'
                "</section>"
            )

        if not sections:
            return (
                '<div class="issue-empty">'
                "No actionable suggestions yet. As grouped issues appear, this tab will attach status and fix guidance."
                "</div>"
            )

        return "".join(sections)

    def _render_issue_card(self, issue: Dict[str, Any], include_solution: bool) -> str:
        issue_type = str(issue.get("type", "log"))
        status = str(issue.get("status", "detected"))
        type_meta = _TYPE_META.get(issue_type, _DEFAULT_META)
        status_meta = _STATUS_META.get(status, _DEFAULT_STATUS_META)
        confidence = issue.get("confidence")
        risk = issue.get("risk")
        latest = issue.get("latest_example") or {}
        suggestion = issue.get("suggestion")
        why = issue.get("why")

        body_parts: List[str] = []
        body_parts.append(
            '<div><div class="issue-label">Latest example</div>'
            f'<div class="issue-example">{_esc(str(latest.get("raw", "")) or "No example captured.")}</div></div>'
        )

        if why:
            body_parts.append(
                '<div><div class="issue-label">Why</div>'
                f'<div class="issue-copy">{_esc(str(why))}</div></div>'
            )

        if include_solution:
            suggestion_copy = suggestion or (
                "No built-in fix is attached yet. Inspect the latest example and surrounding stack or request context."
            )
            body_parts.append(
                '<div><div class="issue-label">Suggested fix</div>'
                f'<div class="issue-copy">{_esc(str(suggestion_copy))}</div></div>'
            )

        meta_parts = [
            f'<span>first seen: {_esc(str(issue.get("first_seen_at", "—"))[:19])}</span>',
            f'<span>last seen: {_esc(str(issue.get("last_seen_at", "—"))[:19])}</span>',
        ]
        if confidence:
            meta_parts.append(f'<span>confidence: {_esc(str(confidence))}</span>')
        if risk:
            meta_parts.append(f'<span>risk: {_esc(str(risk))}</span>')

        return (
            f'<article class="issue-card {status} {"warning" if issue_type in {"warning", "deprecation", "eager_load", "timeout"} else ""}">'
            '<div class="issue-head">'
            f'<div class="issue-title">{_esc(str(issue.get("title", issue_type)))}</div>'
            '<div class="issue-badges">'
            f'<span class="issue-chip type" style="background:{type_meta["badge_bg"]};color:{type_meta["badge_fg"]}">{_esc(type_meta["label"])}</span>'
            f'<span class="issue-chip" style="background:{status_meta["bg"]};color:{status_meta["fg"]}">{_esc(status_meta["label"])}</span>'
            f'<span class="issue-chip count">x{int(issue.get("count", 0))}</span>'
            "</div>"
            "</div>"
            f'<div class="issue-body">{"".join(body_parts)}'
            f'<div class="issue-meta">{"".join(meta_parts)}</div>'
            "</div>"
            "</article>"
        )
