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
    {"id": "requests", "label": "Requests", "kind": "requests", "count_color": "#58a6ff"},
    {"id": "hotspots", "label": "Hotspots", "kind": "hotspots", "count_color": "#fb923c"},
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
    {
        "id": "autofix",
        "label": "Autofix",
        "kind": "issues",
        "issue_view": "autofix",
        "count_color": "#67e8f9",
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
    "applied": {"bg": "#0f3d2e", "fg": "#a7f3d0", "label": "APPLIED"},
    "failed": {"bg": "#4c0519", "fg": "#fecdd3", "label": "FAILED"},
    "cleared": {"bg": "#0f172a", "fg": "#67e8f9", "label": "CLEARED"},
    "ignored": {"bg": "#2d333b", "fg": "#8b949e", "label": "IGNORED"},
}

_DEFAULT_META = _TYPE_META["log"]
_DEFAULT_STATUS_META = _STATUS_META["detected"]
_FLUSH_INTERVAL = 1.0
_TIMELINE_META: Dict[str, Dict[str, str]] = {
    "controller": {"bar": "#60a5fa", "bg": "#0f172a", "fg": "#bfdbfe"},
    "app": {"bar": "#7dd3fc", "bg": "#082f49", "fg": "#bae6fd"},
    "db": {"bar": "#22d3ee", "bg": "#083344", "fg": "#a5f3fc"},
    "cache": {"bar": "#34d399", "bg": "#052e16", "fg": "#bbf7d0"},
    "external": {"bar": "#f97316", "bg": "#431407", "fg": "#fed7aa"},
    "render": {"bar": "#c084fc", "bg": "#2e1065", "fg": "#e9d5ff"},
    "other": {"bar": "#94a3b8", "bg": "#1f2937", "fg": "#e2e8f0"},
}


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
        request_tracker,
        hotspot_tracker,
        autofix_mode: str = "off",
        open_browser: bool = False,
    ) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._html_path: Path = output_dir / f"output-{ts}.html"
        self._data_path: Path = output_dir / f"output-{ts}.js"
        self._project_id = project_id
        self._issue_tracker = issue_tracker
        self._request_tracker = request_tracker
        self._hotspot_tracker = hotspot_tracker
        self._autofix_mode = autofix_mode
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

    def refresh(self) -> None:
        if self._closed:
            return
        self._write_data(final=False)

    def _atomic_write(self, path: Path, content: str) -> None:
        tmp = str(path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)

    def _tab_counts(self, final: bool) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for tab in self._visible_tabs():
            if tab["kind"] == "requests":
                counts[tab["id"]] = self._request_tracker.count()
                continue
            if tab["kind"] == "hotspots":
                counts[tab["id"]] = self._hotspot_tracker.count()
                continue
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
                "autofix": self._render_autofix_cards(),
            },
            "request_view": self._render_request_cards(),
            "hotspot_view": self._render_hotspot_cards(),
        }
        self._atomic_write(
            self._data_path,
            f"window.__DD_PATCH__({json.dumps(payload, ensure_ascii=False)});",
        )

    def _write_shell(self) -> None:
        storage_ns = json.dumps(f"dd:{self._html_path}")
        data_file = json.dumps(self._data_path.name)
        visible_tabs = self._visible_tabs()
        tab_meta_js = json.dumps(
            {
                tab["id"]: {
                    "kind": tab["kind"],
                    "types": tab.get("types"),
                    "issue_view": tab.get("issue_view"),
                }
                for tab in visible_tabs
            }
        )

        tab_buttons = "\n      ".join(
            f'<button class="tab-btn{" active" if tab["id"] == "all" else ""}" '
            f'data-tab="{tab["id"]}" onclick="switchTab(\'{tab["id"]}\')">'
            f'{tab["label"]}'
            f'<span class="tab-cnt" style="color:{tab["count_color"]}">0</span>'
            f"</button>"
            for tab in visible_tabs
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
      overflow-x: hidden;
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
    #issue-view {{
      display: none;
      width: 100%;
      padding: 22px 18px 30px;
    }}
    #issue-view > * {{
      width: min(100%, 1680px);
      margin: 0 auto;
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
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .issue-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr));
      gap: 16px;
      align-items: start;
    }}
    .issue-card {{
      background: #11161d;
      border: 1px solid #30363d;
      border-left: 4px solid #30363d;
      border-radius: 10px;
      padding: 14px;
      box-shadow: 0 0 0 1px rgba(13, 17, 23, 0.08);
      min-width: 0;
    }}
    .issue-card.warning {{ border-left-color: #f97316 }}
    .issue-card.suggested {{ border-left-color: #2ea043 }}
    .issue-card.cleared {{ border-left-color: #67e8f9 }}
    .issue-card.detected {{ border-left-color: #8b949e }}
    .issue-head {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 10px 12px;
      align-items: flex-start;
      margin-bottom: 8px;
      min-width: 0;
    }}
    .issue-title {{
      color: #f0f6fc;
      font-size: 15px;
      font-weight: 700;
      line-height: 1.35;
      min-width: 0;
      flex: 1 1 240px;
      overflow-wrap: anywhere;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .issue-badges {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      justify-content: flex-end;
      min-width: 0;
      flex: 0 1 auto;
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
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .issue-chip.type {{ background: #1f2937; color: #bfdbfe }}
    .issue-chip.count {{ background: #21262d; color: #f0f6fc }}
    .issue-body {{
      color: #c9d1d9;
      display: grid;
      gap: 8px;
      min-width: 0;
    }}
    .issue-label {{
      color: #8b949e;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .5px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .issue-copy {{
      color: #c9d1d9;
      overflow-wrap: anywhere;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .issue-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      color: #8b949e;
      font-size: 11px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .issue-meta span {{
      min-width: 0;
      overflow-wrap: anywhere;
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
      overflow-wrap: anywhere;
      min-width: 0;
    }}
    .issue-empty {{
      color: #6e7681;
      text-align: center;
      padding: 60px 12px;
      border: 1px dashed #30363d;
      border-radius: 12px;
      background: #11161d;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}

    .request-shell {{
      min-width: 0;
    }}
    .request-toolbar {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 14px 18px;
      align-items: flex-end;
      margin-bottom: 16px;
    }}
    .request-search-wrap {{
      display: grid;
      gap: 6px;
      flex: 1 1 320px;
      min-width: min(100%, 320px);
      max-width: 460px;
    }}
    .request-search-label {{
      color: #8b949e;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .5px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .request-search {{
      width: 100%;
      background: #11161d;
      color: #f0f6fc;
      border: 1px solid #30363d;
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 13px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .request-search:focus {{
      outline: none;
      border-color: #58a6ff;
      box-shadow: 0 0 0 3px rgba(88, 166, 255, 0.18);
    }}
    .request-list {{
      display: grid;
      gap: 14px;
    }}
    .request-card {{
      background: #11161d;
      border: 1px solid #30363d;
      border-left: 4px solid #58a6ff;
      border-radius: 12px;
      overflow: hidden;
      min-width: 0;
    }}
    .request-card[open] {{
      border-color: #3b82f6;
    }}
    .request-summary {{
      list-style: none;
      cursor: pointer;
      padding: 14px 16px;
      display: grid;
      gap: 10px;
    }}
    .request-summary::-webkit-details-marker {{
      display: none;
    }}
    .request-head {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 10px 12px;
      align-items: flex-start;
      min-width: 0;
    }}
    .request-title {{
      flex: 1 1 280px;
      min-width: 0;
      color: #f0f6fc;
      font-size: 15px;
      font-weight: 700;
      line-height: 1.35;
      overflow-wrap: anywhere;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .request-badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      justify-content: flex-end;
      min-width: 0;
      flex: 0 1 auto;
    }}
    .request-chip {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .3px;
      background: #21262d;
      color: #c9d1d9;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .request-chip.live {{ background: #0b2f1a; color: #86efac; }}
    .request-chip.done {{ background: #0f172a; color: #93c5fd; }}
    .request-chip.warn {{ background: #3f3000; color: #fde68a; }}
    .request-chip.error {{ background: #4c0519; color: #fecdd3; }}
    .request-chip.method {{ background: #0e4f5c; color: #a5f3fc; }}
    .request-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
      color: #8b949e;
      font-size: 12px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .request-meta span {{
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    .request-detail {{
      border-top: 1px solid #21262d;
      background: #0f141b;
      padding: 12px 16px 16px;
      display: grid;
      gap: 12px;
    }}
    .request-timeline {{
      display: grid;
      gap: 10px;
    }}
    .request-timeline-head {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 10px;
      align-items: baseline;
      justify-content: space-between;
    }}
    .request-timeline-title {{
      color: #f0f6fc;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .4px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .request-timeline-copy {{
      color: #8b949e;
      font-size: 12px;
      line-height: 1.45;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .request-breakdown {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .request-breakdown-chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .2px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .request-breakdown-chip strong {{
      font-weight: 800;
    }}
    .request-waterfall {{
      display: grid;
      gap: 8px;
    }}
    .request-segment {{
      display: grid;
      grid-template-columns: minmax(0, 190px) minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
    }}
    .request-segment-label {{
      color: #c9d1d9;
      font-size: 12px;
      min-width: 0;
      overflow-wrap: anywhere;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .request-segment-track {{
      position: relative;
      height: 12px;
      border-radius: 999px;
      background: #11161d;
      border: 1px solid #21262d;
      overflow: hidden;
    }}
    .request-segment-bar {{
      position: absolute;
      top: 0;
      height: 100%;
      border-radius: 999px;
      min-width: 8px;
    }}
    .request-segment-duration {{
      color: #8b949e;
      font-size: 12px;
      white-space: nowrap;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .request-lines {{
      padding-top: 4px;
      display: grid;
      gap: 10px;
      max-height: 460px;
      overflow: auto;
    }}
    .request-line {{
      display: grid;
      grid-template-columns: 72px auto minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      min-width: 0;
    }}
    .request-line-time {{
      color: #8b949e;
      white-space: nowrap;
    }}
    .request-line-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .3px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      white-space: nowrap;
    }}
    .request-line-raw {{
      min-width: 0;
      color: #c9d1d9;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .hotspot-shell {{
      min-width: 0;
    }}
    .hotspot-list {{
      display: grid;
      gap: 12px;
    }}
    .hotspot-card {{
      background: #11161d;
      border: 1px solid #30363d;
      border-left: 4px solid #fb923c;
      border-radius: 12px;
      padding: 14px 16px;
      display: grid;
      gap: 10px;
    }}
    .hotspot-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px 14px;
      flex-wrap: wrap;
    }}
    .hotspot-rank {{
      color: #fb923c;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .4px;
      text-transform: uppercase;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .hotspot-title {{
      color: #f0f6fc;
      font-size: 15px;
      font-weight: 700;
      line-height: 1.35;
      overflow-wrap: anywhere;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .hotspot-summary {{
      color: #f0f6fc;
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .hotspot-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      color: #8b949e;
      font-size: 12px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .hotspot-meta span {{
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    .hotspot-badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .hotspot-badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 3px 9px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .2px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .hotspot-badge.slow {{ background: #431407; color: #fed7aa; }}
    .hotspot-badge.retry {{ background: #3b0764; color: #e9d5ff; }}
    .hotspot-badge.warn {{ background: #3f3000; color: #fde68a; }}
    .hotspot-badge.error {{ background: #4c0519; color: #fecdd3; }}
    .hotspot-badge.info {{ background: #082f49; color: #bae6fd; }}
    .hotspot-badge.ignored {{ background: #1f2937; color: #cbd5e1; }}

    @media (max-width: 760px) {{
      #issue-view {{
        padding: 14px 12px 22px;
      }}

      .issue-grid {{
        grid-template-columns: minmax(0, 1fr);
        gap: 12px;
      }}

      .issue-head {{
        flex-direction: column;
        align-items: stretch;
      }}

      .issue-badges {{
        justify-content: flex-start;
      }}

      .request-toolbar {{
        align-items: stretch;
      }}

      .request-search-wrap {{
        max-width: none;
      }}

      .request-badges {{
        justify-content: flex-start;
      }}

      .request-line {{
        grid-template-columns: minmax(0, 1fr);
        gap: 6px;
      }}

      .request-segment {{
        grid-template-columns: minmax(0, 1fr);
        gap: 6px;
      }}
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
    var latestRequestView = '';
    var latestHotspotView = '';
    var requestSearchTerm = sessionStorage.getItem(STORAGE_NS + ':request-search') || '';
    var issueViewPointerActive = false;
    var issueViewFocusActive = false;
    var pendingInteractivePanelRender = false;
    var requestOpenStateDirty = sessionStorage.getItem(STORAGE_NS + ':request-open-dirty') === '1';
    var requestExpandedIds = requestOpenStateDirty
      ? JSON.parse(sessionStorage.getItem(STORAGE_NS + ':request-open') || '[]')
      : [];
    var requestScrollStateDirty = sessionStorage.getItem(STORAGE_NS + ':request-scroll-dirty') === '1';
    var requestScrollPositions = requestScrollStateDirty
      ? JSON.parse(sessionStorage.getItem(STORAGE_NS + ':request-scroll') || '{{}}')
      : {{}};

    function captureRequestViewState() {{
      requestExpandedIds = [];
      requestScrollPositions = {{}};

      document.querySelectorAll('.request-card').forEach(function(card) {{
        var requestId = card.dataset.requestId || '';
        if (!requestId) return;

        if (card.open) {{
          requestExpandedIds.push(requestId);
        }}

        var lines = card.querySelector('.request-lines');
        if (lines) {{
          requestScrollPositions[requestId] = lines.scrollTop || 0;
        }}
      }});

      requestOpenStateDirty = true;
      requestScrollStateDirty = true;
      sessionStorage.setItem(STORAGE_NS + ':request-open-dirty', '1');
      sessionStorage.setItem(STORAGE_NS + ':request-scroll-dirty', '1');
      sessionStorage.setItem(STORAGE_NS + ':request-open', JSON.stringify(requestExpandedIds));
      sessionStorage.setItem(STORAGE_NS + ':request-scroll', JSON.stringify(requestScrollPositions));
    }}

    function isIssuePanelInteractive() {{
      return issueViewPointerActive || issueViewFocusActive;
    }}

    function shouldDeferIssuePanelRender() {{
      var tab = TAB_META[activeTab] || TAB_META.all;
      return (tab.kind === 'issues' || tab.kind === 'requests' || tab.kind === 'hotspots') && isIssuePanelInteractive();
    }}

    function flushDeferredIssuePanelRender() {{
      if (!pendingInteractivePanelRender || shouldDeferIssuePanelRender()) return;
      pendingInteractivePanelRender = false;
      renderActiveView();
    }}

    function restoreRequestViewState() {{
      if (requestOpenStateDirty) {{
        document.querySelectorAll('.request-card').forEach(function(card) {{
          card.open = requestExpandedIds.indexOf(card.dataset.requestId || '') !== -1;
        }});
      }}

      if (requestScrollStateDirty) {{
        document.querySelectorAll('.request-card').forEach(function(card) {{
          var requestId = card.dataset.requestId || '';
          var lines = card.querySelector('.request-lines');
          if (!requestId || !lines) return;

          var saved = requestScrollPositions[requestId];
          if (typeof saved === 'number') {{
            lines.scrollTop = saved;
          }}
        }});
      }}
    }}

    function applyRequestSearch() {{
      var empty = document.getElementById('request-empty');
      var shown = 0;
      var term = requestSearchTerm.toLowerCase().trim();

      document.querySelectorAll('.request-card').forEach(function(card) {{
        var haystack = (card.dataset.search || '').toLowerCase();
        var show = !term || haystack.indexOf(term) !== -1;
        card.style.display = show ? '' : 'none';
        if (show) shown++;
      }});

      if (empty) {{
        empty.style.display = shown === 0 ? 'block' : 'none';
      }}
    }}

    function renderActiveView() {{
      var tab = TAB_META[activeTab] || TAB_META.all;
      var eventView = document.getElementById('event-view');
      var issueView = document.getElementById('issue-view');

      if (tab.kind === 'requests') {{
        eventView.style.display = 'none';
        issueView.style.display = 'block';
        issueView.innerHTML = latestRequestView || '<div class="request-shell"><div class="issue-empty">No request traces detected yet.</div></div>';
        var requestSearch = document.getElementById('request-search');
        if (requestSearch) requestSearch.value = requestSearchTerm;
        restoreRequestViewState();
        applyRequestSearch();
        return;
      }}

      if (tab.kind === 'hotspots') {{
        eventView.style.display = 'none';
        issueView.style.display = 'block';
        issueView.innerHTML = latestHotspotView || '<div class="hotspot-shell"><div class="issue-empty">No endpoint hotspots detected yet.</div></div>';
        return;
      }}

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
      if (activeTab === 'requests') {{
        captureRequestViewState();
      }}
      appendRows(data.rows, data.total);
      latestIssueViews = data.issue_views || latestIssueViews;
      latestRequestView = data.request_view || latestRequestView;
      latestHotspotView = data.hotspot_view || latestHotspotView;
      updateCounts(data.counts || {{}});
      if (shouldDeferIssuePanelRender()) {{
        pendingInteractivePanelRender = true;
      }} else {{
        pendingInteractivePanelRender = false;
        renderActiveView();
      }}

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

    document.addEventListener('input', function(e) {{
      if (e.target && e.target.id === 'request-search') {{
        requestSearchTerm = e.target.value || '';
        sessionStorage.setItem(STORAGE_NS + ':request-search', requestSearchTerm);
        applyRequestSearch();
      }}
    }});

    document.addEventListener('toggle', function(e) {{
      if (e.target && e.target.classList && e.target.classList.contains('request-card')) {{
        captureRequestViewState();
      }}
    }}, true);

    document.addEventListener('scroll', function(e) {{
      if (e.target && e.target.classList && e.target.classList.contains('request-lines')) {{
        captureRequestViewState();
      }}
    }}, true);

    window.addEventListener('DOMContentLoaded', function() {{
      var issueViewEl = document.getElementById('issue-view');
      if (issueViewEl) {{
        issueViewEl.addEventListener('pointerenter', function() {{
          issueViewPointerActive = true;
        }});

        issueViewEl.addEventListener('pointerleave', function() {{
          issueViewPointerActive = false;
          flushDeferredIssuePanelRender();
        }});

        issueViewEl.addEventListener('focusin', function() {{
          issueViewFocusActive = true;
        }});

        issueViewEl.addEventListener('focusout', function() {{
          window.setTimeout(function() {{
            issueViewFocusActive = issueViewEl.contains(document.activeElement);
            flushDeferredIssuePanelRender();
          }}, 0);
        }});
      }}

      switchTab(activeTab);
      loadData();
      pollTimer = setInterval(loadData, 2000);
    }});
  </script>
</body>
</html>"""

        self._atomic_write(self._html_path, html)

    def _visible_tabs(self) -> List[Dict[str, Any]]:
        if self._autofix_mode == "apply":
            return list(_TABS)
        return [tab for tab in _TABS if tab["id"] != "autofix"]

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

            if ev_type == "eager_load" and ev.get("bullet_mode"):
                details_parts.append(
                    f'<span class="d-key">mode</span>'
                    f'<span class="d-sep">=</span>'
                    f'<span style="color:#ddd6fe">{_esc(str(ev["bullet_mode"]).upper())}</span>'
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

            raw_text = str(ev.get("raw") or "")
            raw_full = _esc(raw_text)
            raw_preview = raw_text.split("\n", 1)[0]
            raw_short = _esc(raw_preview[:120])

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
                "Suggestions are attached to canonical issue fingerprints, so repeated warnings stay in one place while counts keep climbing. When autofix is enabled, cards also show patch readiness and apply results."
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

    def _render_autofix_cards(self) -> str:
        issues = self._issue_tracker.autofix_issues()
        if not issues:
            return (
                '<div class="issue-empty">'
                "No autofix candidates are attached to the current session."
                "</div>"
            )

        applied = [
            issue for issue in issues if str((issue.get("autofix") or {}).get("status")) == "applied"
        ]
        ready = [
            issue for issue in issues if str((issue.get("autofix") or {}).get("status")) == "available"
        ]
        blocked = [
            issue
            for issue in issues
            if str((issue.get("autofix") or {}).get("status")) in {"failed", "unavailable"}
        ]

        sections: List[str] = []
        if ready:
            ready_cards = "\n".join(
                self._render_issue_card(issue, include_solution=True)
                for issue in ready
            )
            sections.append(
                '<section class="issue-section">'
                '<div class="issue-section-title">Ready auto patches</div>'
                '<div class="issue-section-copy">'
                "These issues have a concrete built-in patch plan. In apply mode, eligible rules run after the wrapped command exits."
                "</div>"
                f'<div class="issue-grid">{ready_cards}</div>'
                "</section>"
            )

        if applied:
            applied_cards = "\n".join(
                self._render_issue_card(issue, include_solution=True)
                for issue in applied
            )
            sections.append(
                '<section class="issue-section">'
                '<div class="issue-section-title">Applied patches</div>'
                '<div class="issue-section-copy">'
                "These fixes were written to disk by devdoctor during the current session."
                "</div>"
                f'<div class="issue-grid">{applied_cards}</div>'
                "</section>"
            )

        if blocked:
            blocked_cards = "\n".join(
                self._render_issue_card(issue, include_solution=True)
                for issue in blocked
            )
            sections.append(
                '<section class="issue-section">'
                '<div class="issue-section-title">Needs attention</div>'
                '<div class="issue-section-copy">'
                "These issues had an autofix plan, but devdoctor could not apply or verify it safely."
                "</div>"
                f'<div class="issue-grid">{blocked_cards}</div>'
                "</section>"
            )

        return "".join(sections)

    def _render_hotspot_cards(self) -> str:
        hotspots = self._hotspot_tracker.hotspots()
        if not hotspots:
            return (
                '<div class="hotspot-shell">'
                '<div class="issue-empty">No endpoint hotspots detected yet.</div>'
                "</div>"
            )

        cards = "\n".join(
            self._render_hotspot_card(index + 1, hotspot)
            for index, hotspot in enumerate(hotspots[:10])
        )
        return (
            '<div class="hotspot-shell">'
            '<section class="issue-section">'
            '<div class="request-toolbar">'
            '<div>'
            '<div class="issue-section-title">Endpoint hotspots</div>'
            '<div class="issue-section-copy">'
            "Ranked across all saved DevDoctor sessions for this project plus the current live session."
            "</div>"
            "</div>"
            "</div>"
            f'<div class="hotspot-list">{cards}</div>'
            "</section>"
            "</div>"
        )

    def _render_hotspot_card(self, rank: int, hotspot: Dict[str, Any]) -> str:
        endpoint = _esc(str(hotspot.get("endpoint") or "Unknown endpoint"))
        summary = _esc(str(hotspot.get("summary") or "active"))

        meta = [
            f'<span>samples: {_esc(str(hotspot.get("count") or 0))}</span>',
            f'<span>sessions: {_esc(str(hotspot.get("session_count") or 0))}</span>',
        ]
        if hotspot.get("avg_ms") is not None:
            meta.append(f'<span>avg: {_esc(self._format_ms(hotspot.get("avg_ms")))} </span>')
        if hotspot.get("max_ms") is not None:
            meta.append(f'<span>max: {_esc(self._format_ms(hotspot.get("max_ms")))} </span>')

        badges = []
        if hotspot.get("p95_ms") is not None:
            badges.append(
                f'<span class="hotspot-badge slow">P95 {_esc(self._format_ms(hotspot.get("p95_ms")))} </span>'
            )
        if hotspot.get("retry_count"):
            retries = int(hotspot.get("retry_count") or 0)
            label = "retry" if retries == 1 else "retries"
            badges.append(
                f'<span class="hotspot-badge retry">{retries} {label}</span>'
            )
        if hotspot.get("error_total"):
            badges.append(
                f'<span class="hotspot-badge error">{_esc(str(hotspot.get("error_total")))} errors</span>'
            )
        if hotspot.get("warning_total"):
            badges.append(
                f'<span class="hotspot-badge warn">{_esc(str(hotspot.get("warning_total")))} warnings</span>'
            )
        if hotspot.get("dominant_label") and hotspot.get("dominant_ms") is not None:
            badges.append(
                f'<span class="hotspot-badge info">dominant {_esc(str(hotspot.get("dominant_label")))} {_esc(self._format_ms(hotspot.get("dominant_ms")))} </span>'
            )
        if hotspot.get("ignored"):
            badges.append('<span class="hotspot-badge ignored">ignored by noise rules</span>')

        return (
            '<article class="hotspot-card">'
            '<div class="hotspot-head">'
            '<div>'
            f'<div class="hotspot-rank">#{rank} hotspot</div>'
            f'<div class="hotspot-title">{endpoint}</div>'
            "</div>"
            f'<div class="hotspot-summary">{summary}</div>'
            "</div>"
            f'<div class="hotspot-meta">{"".join(meta)}</div>'
            f'<div class="hotspot-badges">{"".join(badges)}</div>'
            "</article>"
        )

    def _render_request_cards(self) -> str:
        traces = self._request_tracker.traces()
        if not traces:
            return (
                '<div class="request-shell">'
                '<div class="issue-empty">No request traces detected yet.</div>'
                "</div>"
            )

        cards = "\n".join(self._render_request_card(trace) for trace in traces)
        return (
            '<div class="request-shell">'
            '<div class="request-toolbar">'
            '<div>'
            '<div class="issue-section-title">Request traces</div>'
            '<div class="issue-section-copy">'
            "Logs are grouped by request id so each GET or POST flow stays together even when Rails interleaves the lines."
            "</div>"
            "</div>"
            '<label class="request-search-wrap">'
            '<span class="request-search-label">Search request</span>'
            '<input id="request-search" class="request-search" type="search" '
            'placeholder="Search GET /api..., controller, request id, actor" />'
            "</label>"
            "</div>"
            '<div id="request-empty" class="issue-empty" style="display:none">'
            "No request traces match this search."
            "</div>"
            f'<div class="request-list">{cards}</div>'
            "</div>"
        )

    def _render_request_card(self, trace: Dict[str, Any]) -> str:
        title = _esc(str(trace.get("title") or trace.get("request_id") or "Request"))
        request_id = _esc(str(trace.get("request_id", "")))
        search_text = _esc(str(trace.get("search_text", "")))
        open_attr = " open" if not trace.get("completed") or trace.get("error_count") else ""
        duration = self._format_duration(trace.get("duration"))
        status_chip = self._render_request_chip(
            "DONE" if trace.get("completed") else "LIVE",
            "done" if trace.get("completed") else "live",
        )

        badges = [
            status_chip,
            self._render_request_chip(str(trace.get("method") or "REQ"), "method"),
        ]
        if duration:
            badges.append(self._render_request_chip(duration, "done"))
        if trace.get("query_count"):
            badges.append(self._render_request_chip(f'{trace["query_count"]} queries', "method"))
        if trace.get("warning_count"):
            badges.append(self._render_request_chip(f'{trace["warning_count"]} warnings', "warn"))
        if trace.get("error_count"):
            badges.append(self._render_request_chip(f'{trace["error_count"]} errors', "error"))

        meta: List[str] = [f"<span>request: {request_id}</span>"]
        if trace.get("controller"):
            action = f'#{trace["action"]}' if trace.get("action") else ""
            meta.append(f'<span>controller: {_esc(str(trace["controller"]))}{_esc(action)}</span>')
        if trace.get("actor"):
            meta.append(f'<span>actor: {_esc(str(trace["actor"]))}</span>')
        if trace.get("status"):
            status_text = f' {_esc(str(trace.get("status_text") or ""))}'.rstrip()
            meta.append(f'<span>status: {_esc(str(trace["status"]))}{status_text}</span>')

        lines = "\n".join(
            self._render_request_event(event)
            for event in trace.get("events", [])
        )
        timeline = self._render_request_timeline(trace)

        return (
            f'<details class="request-card" data-request-id="{request_id}" data-search="{search_text}"{open_attr}>'
            '<summary class="request-summary">'
            '<div class="request-head">'
            f'<div class="request-title">{title}</div>'
            f'<div class="request-badges">{"".join(badges)}</div>'
            "</div>"
            f'<div class="request-meta">{"".join(meta)}</div>'
            "</summary>"
            '<div class="request-detail">'
            f"{timeline}"
            f'<div class="request-lines">{lines}</div>'
            "</div>"
            "</details>"
        )

    def _render_request_timeline(self, trace: Dict[str, Any]) -> str:
        segments = list(trace.get("timeline") or [])
        breakdown = list(trace.get("timeline_breakdown") or [])
        total_ms = self._coerce_ms(trace.get("timeline_total_ms"))
        highlight = trace.get("timeline_highlight") or {}

        if not segments or total_ms in (None, 0.0):
            return (
                '<div class="request-timeline">'
                '<div class="request-timeline-title">Request timeline</div>'
                '<div class="request-timeline-copy">'
                "Timed operations will appear here once this request logs DB, cache, render, or dependency durations."
                "</div>"
                "</div>"
            )

        summary_bits = [
            self._render_request_breakdown_chip("total", total_ms, "other")
        ]
        for item in breakdown[:5]:
            summary_bits.append(
                self._render_request_breakdown_chip(
                    str(item.get("label") or item.get("kind") or "other"),
                    self._coerce_ms(item.get("duration_ms")) or 0.0,
                    str(item.get("kind") or "other"),
                )
            )

        if highlight:
            highlight_label = str(highlight.get("label") or highlight.get("kind") or "segment")
            highlight_duration = self._coerce_ms(highlight.get("duration_ms")) or 0.0
            summary_bits.append(
                self._render_request_breakdown_chip(
                    f"slowest: {highlight_label}",
                    highlight_duration,
                    str(highlight.get("kind") or "other"),
                )
            )

        segment_rows = "\n".join(
            self._render_request_timeline_segment(segment, total_ms)
            for segment in segments
        )

        return (
            '<div class="request-timeline">'
            '<div class="request-timeline-head">'
            '<div class="request-timeline-title">Request timeline</div>'
            '<div class="request-timeline-copy">'
            "Local waterfall inferred from timed log lines inside this request."
            "</div>"
            "</div>"
            f'<div class="request-breakdown">{"".join(summary_bits)}</div>'
            f'<div class="request-waterfall">{segment_rows}</div>'
            "</div>"
        )

    def _render_request_event(self, event: Dict[str, Any]) -> str:
        event_type = str(event.get("type", "log"))
        stage = str(event.get("stage", "event"))
        meta = _TYPE_META.get(event_type, _DEFAULT_META)
        label = meta["label"]
        badge_bg = meta["badge_bg"]
        badge_fg = meta["badge_fg"]
        if event_type == "log" and stage != "event":
            label = stage.upper()
            badge_bg = "#1f2937"
            badge_fg = "#cbd5e1"

        ts = self._short_ts(str(event.get("ts", "")))
        raw = _esc(str(event.get("raw", "")))
        return (
            '<div class="request-line">'
            f'<div class="request-line-time">{ts}</div>'
            f'<div><span class="request-line-badge" style="background:{badge_bg};color:{badge_fg}">{_esc(label)}</span></div>'
            f'<div class="request-line-raw">{raw}</div>'
            "</div>"
        )

    def _render_request_chip(self, label: str, variant: str) -> str:
        return f'<span class="request-chip {variant}">{_esc(label)}</span>'

    def _render_request_breakdown_chip(self, label: str, duration_ms: float, kind: str) -> str:
        meta = _TIMELINE_META.get(kind, _TIMELINE_META["other"])
        return (
            f'<span class="request-breakdown-chip" style="background:{meta["bg"]};color:{meta["fg"]}">'
            f'{_esc(label)} <strong>{_esc(self._format_ms(duration_ms))}</strong>'
            "</span>"
        )

    def _render_request_timeline_segment(self, segment: Dict[str, Any], total_ms: float) -> str:
        kind = str(segment.get("kind") or "other")
        meta = _TIMELINE_META.get(kind, _TIMELINE_META["other"])
        label = _esc(str(segment.get("label") or kind))
        duration_ms = self._coerce_ms(segment.get("duration_ms")) or 0.0
        start_offset_ms = self._coerce_ms(segment.get("start_offset_ms")) or 0.0
        total = max(total_ms, duration_ms, 1.0)
        width_pct = max((duration_ms / total) * 100.0, 2.0)
        max_left = max(100.0 - width_pct, 0.0)
        left_pct = min((start_offset_ms / total) * 100.0, max_left)

        return (
            '<div class="request-segment">'
            f'<div class="request-segment-label">{label}</div>'
            '<div class="request-segment-track">'
            f'<div class="request-segment-bar" style="left:{left_pct:.2f}%;width:{width_pct:.2f}%;background:{meta["bar"]}"></div>'
            "</div>"
            f'<div class="request-segment-duration">{_esc(self._format_ms(duration_ms))}</div>'
            "</div>"
        )

    def _format_duration(self, duration: Optional[Any]) -> str:
        if duration in (None, ""):
            return ""
        try:
            return f"{float(duration):.1f}".rstrip("0").rstrip(".") + "ms"
        except (TypeError, ValueError):
            return f"{duration}ms"

    def _format_ms(self, duration_ms: Optional[float]) -> str:
        if duration_ms in (None, 0):
            return "0ms" if duration_ms == 0 else ""
        return f"{float(duration_ms):.1f}".rstrip("0").rstrip(".") + "ms"

    def _coerce_ms(self, value: Optional[Any]) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _short_ts(self, ts: str) -> str:
        return ts[11:19] if len(ts) >= 19 else ts

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
        autofix = issue.get("autofix") or {}

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

        if include_solution and autofix:
            autofix_lines: List[str] = []
            if autofix.get("summary"):
                autofix_lines.append(str(autofix["summary"]))
            elif autofix.get("reason"):
                autofix_lines.append(str(autofix["reason"]))

            autofix_meta: List[str] = []
            if autofix.get("status"):
                autofix_meta.append(f'status: {_esc(str(autofix["status"]))}')
            if autofix.get("rule_id"):
                autofix_meta.append(f'rule: {_esc(str(autofix["rule_id"]))}')
            if autofix.get("file"):
                autofix_meta.append(f'file: {_esc(str(autofix["file"]))}')
            if autofix.get("applied_at"):
                autofix_meta.append(f'applied: {_esc(str(autofix["applied_at"]))[:19]}')
            if autofix.get("verification_status"):
                autofix_meta.append(
                    f'verify: {_esc(str(autofix["verification_status"]))}'
                )
            if autofix.get("verification_cmd"):
                autofix_meta.append(
                    f'check: {_esc(str(autofix["verification_cmd"]))}'
                )

            block = (
                '<div><div class="issue-label">Auto patch</div>'
                f'<div class="issue-copy">{_esc(" ".join(autofix_lines) or "No automatic patch is attached to this issue.")}</div>'
            )
            if autofix_meta:
                block += f'<div class="issue-meta">{"".join(f"<span>{item}</span>" for item in autofix_meta)}</div>'
            if autofix.get("patch_preview"):
                block += f'<div class="issue-example">{_esc(str(autofix["patch_preview"]))}</div>'
            elif autofix.get("verification_output"):
                block += f'<div class="issue-example">{_esc(str(autofix["verification_output"]))}</div>'
            block += "</div>"
            body_parts.append(block)

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
