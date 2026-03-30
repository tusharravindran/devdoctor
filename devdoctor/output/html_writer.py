"""HTML output writer: renders live log events to a self-refreshing HTML file."""

import os
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils import color

# Colour / badge config per event type
_TYPE_META: Dict[str, Dict[str, str]] = {
    "error":   {"bar": "#ff5f5f", "badge_bg": "#c0392b", "badge_fg": "#fff", "label": "ERROR"},
    "latency": {"bar": "#ffd700", "badge_bg": "#7d6608", "badge_fg": "#ffe", "label": "LATENCY"},
    "query":   {"bar": "#5fafff", "badge_bg": "#1a5276", "badge_fg": "#fff", "label": "QUERY"},
    "log":     {"bar": "#3d4450", "badge_bg": "#2d333b", "badge_fg": "#8b949e", "label": "LOG"},
}
_DEFAULT_META = _TYPE_META["log"]

# How often to flush to disk while events are streaming (seconds)
_FLUSH_INTERVAL = 1.0


def _esc(s: Optional[str]) -> str:
    if not s:
        return ""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


class HtmlWriter:
    """
    Writes a self-refreshing HTML file that shows parsed log events in real time.

    Usage
    -----
    hw = HtmlWriter(Path("/some/dir"), project_id="myapp-ab12cd34")
    hw.add_event(event_dict)   # call for each event
    hw.close()                  # called on exit; writes final page (no more refresh)
    """

    def __init__(self, output_dir: Path, project_id: str, open_browser: bool = False):
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._path: Path = output_dir / f"output-{ts}.html"
        self._project_id = project_id
        self._session_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._events: List[Dict[str, Any]] = []
        self._last_flush: float = 0.0
        # Write an empty "waiting" page immediately so the file exists
        self._write(final=False)
        print(color.success(f"HTML output → {self._path}"), flush=True)
        if open_browser:
            webbrowser.open(self._path.as_uri())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_event(self, event: Dict[str, Any]) -> None:
        enriched = dict(event)
        enriched["_ts"] = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._events.append(enriched)
        if time.monotonic() - self._last_flush >= _FLUSH_INTERVAL:
            self._write(final=False)

    def close(self) -> None:
        """Write the final page (removes auto-refresh, marks session DONE)."""
        self._write(final=True)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _write(self, final: bool) -> None:
        self._last_flush = time.monotonic()
        html = self._render(final)
        tmp = str(self._path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(html)
        os.replace(tmp, self._path)

    def _render(self, final: bool) -> str:
        error_count   = sum(1 for e in self._events if e.get("type") == "error")
        latency_count = sum(1 for e in self._events if e.get("type") == "latency")
        query_count   = sum(1 for e in self._events if e.get("type") == "query")
        total         = len(self._events)

        status_label = "DONE" if final else "LIVE"
        status_color = "#8b949e" if final else "#2ea043"

        # meta-refresh tag (removed on final write to stop reloading)
        refresh_tag = "" if final else '<meta http-equiv="refresh" content="2">'

        rows = self._render_rows()

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  {refresh_tag}
  <title>devdoctor — {_esc(self._project_id)}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0 }}

    body {{
      background: #0d1117;
      color: #c9d1d9;
      font-family: 'SF Mono', 'Fira Code', Consolas, 'Courier New', monospace;
      font-size: 13px;
      line-height: 1.55;
    }}

    /* ── header ── */
    header {{
      position: sticky;
      top: 0;
      z-index: 20;
      background: #161b22;
      border-bottom: 1px solid #30363d;
      padding: 10px 18px;
      display: flex;
      align-items: center;
      gap: 14px;
      flex-wrap: wrap;
    }}
    header h1 {{
      font-size: 14px;
      color: #58a6ff;
      letter-spacing: .4px;
      white-space: nowrap;
    }}
    .pill {{
      display: inline-block;
      padding: 2px 9px;
      border-radius: 20px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .4px;
      background: {status_color};
      color: #000;
    }}
    .meta {{
      color: #8b949e;
      font-size: 12px;
    }}
    .meta b {{ color: #c9d1d9 }}

    /* ── stats row ── */
    .stats {{
      margin-left: auto;
      display: flex;
      gap: 18px;
      font-size: 12px;
    }}
    .s-total   {{ color: #8b949e }}
    .s-error   {{ color: #ff7b72 }}
    .s-latency {{ color: #ffd700 }}
    .s-query   {{ color: #79c0ff }}

    /* ── table ── */
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    thead th {{
      position: sticky;
      top: 53px;
      background: #161b22;
      color: #8b949e;
      font-weight: 600;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .5px;
      padding: 7px 14px;
      text-align: left;
      border-bottom: 1px solid #30363d;
    }}
    tbody tr {{ border-bottom: 1px solid #161b22 }}
    tbody tr:hover td {{ background: #1c2128 }}
    td {{
      padding: 5px 14px;
      vertical-align: top;
    }}

    /* ── left-border accent per type ── */
    .row-error   td:first-child {{ border-left: 3px solid #ff5f5f }}
    .row-latency td:first-child {{ border-left: 3px solid #ffd700 }}
    .row-query   td:first-child {{ border-left: 3px solid #5fafff }}
    .row-log     td:first-child {{ border-left: 3px solid #30363d }}

    /* ── cells ── */
    .c-ts    {{ color: #8b949e; white-space: nowrap; width: 80px }}
    .c-type  {{ width: 90px; white-space: nowrap }}
    .badge {{
      display: inline-block;
      padding: 1px 7px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .3px;
    }}
    .c-details {{ color: #e6edf3; min-width: 260px }}
    .d-msg  {{ color: #ff7b72 }}
    .d-key  {{ color: #79c0ff }}
    .d-val  {{ color: #c9d1d9 }}
    .d-sep  {{ color: #484f58; margin: 0 5px }}
    .c-raw  {{
      color: #484f58;
      max-width: 480px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .dim {{ color: #484f58 }}

    /* ── empty state ── */
    .empty-row td {{
      text-align: center;
      color: #484f58;
      padding: 60px 0;
      font-size: 14px;
      border: none;
    }}

    /* ── footer ── */
    footer {{
      color: #484f58;
      font-size: 11px;
      padding: 14px 18px;
      border-top: 1px solid #21262d;
      margin-top: 6px;
    }}
  </style>
  <script>
    // Preserve vertical scroll across meta-refresh reloads
    (function() {{
      var key = 'devdoctor_scroll';
      window.addEventListener('beforeunload', function() {{
        sessionStorage.setItem(key, document.documentElement.scrollTop);
      }});
      window.addEventListener('DOMContentLoaded', function() {{
        var pos = sessionStorage.getItem(key);
        if (pos) {{
          document.documentElement.scrollTop = parseInt(pos, 10);
          sessionStorage.removeItem(key);
        }}
      }});
    }})();
  </script>
</head>
<body>
  <header>
    <h1>devdoctor</h1>
    <span class="pill">{status_label}</span>
    <span class="meta">
      project: <b>{_esc(self._project_id)}</b>
      &nbsp;&middot;&nbsp;
      session: <b>{self._session_ts}</b>
    </span>
    <div class="stats">
      <span class="s-total">{total} events</span>
      <span class="s-error">{error_count} errors</span>
      <span class="s-latency">{latency_count} latency</span>
      <span class="s-query">{query_count} queries</span>
    </div>
  </header>

  <table>
    <thead>
      <tr>
        <th class="c-ts">Time</th>
        <th class="c-type">Type</th>
        <th class="c-details">Details</th>
        <th class="c-raw">Raw log</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>

  <footer>
    {self._path.name} &nbsp;&middot;&nbsp; devdoctor {status_label.lower()}
    {"&nbsp;&middot;&nbsp; auto-refresh every 2s" if not final else ""}
  </footer>
</body>
</html>"""

    def _render_rows(self) -> str:
        if not self._events:
            return '<tr class="empty-row"><td colspan="4">Waiting for log events&hellip;</td></tr>'

        parts: List[str] = []
        for ev in reversed(self._events):  # newest first
            ev_type = ev.get("type", "log")
            meta    = _TYPE_META.get(ev_type, _DEFAULT_META)

            ts      = _esc(ev.get("_ts", ""))
            badge   = (
                f'<span class="badge" '
                f'style="background:{meta["badge_bg"]};color:{meta["badge_fg"]}">'
                f'{meta["label"]}</span>'
            )

            # Build details cell
            detail_parts: List[str] = []
            if ev.get("message"):
                detail_parts.append(f'<span class="d-msg">{_esc(ev["message"])}</span>')
            if ev.get("duration"):
                detail_parts.append(
                    f'<span class="d-key">duration</span>'
                    f'<span class="d-sep">=</span>'
                    f'<span class="d-val">{_esc(ev["duration"])}ms</span>'
                )
            if ev.get("table"):
                detail_parts.append(
                    f'<span class="d-key">table</span>'
                    f'<span class="d-sep">=</span>'
                    f'<span class="d-val">{_esc(ev["table"])}</span>'
                )
            details = (
                ' &nbsp; '.join(detail_parts)
                if detail_parts
                else '<span class="dim">—</span>'
            )

            raw = _esc(ev.get("raw", ""))

            parts.append(
                f'<tr class="row-{ev_type}">'
                f'<td class="c-ts">{ts}</td>'
                f'<td class="c-type">{badge}</td>'
                f'<td class="c-details">{details}</td>'
                f'<td class="c-raw" title="{raw}">{raw}</td>'
                f'</tr>'
            )

        return "\n      ".join(parts)
