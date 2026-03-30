"""Built-in regex patterns for log parsing.

Patterns are tried in order — first match wins.
All patterns should use named capture groups so the engine can populate
the normalised event fields (message, duration, table).
"""

DEFAULT_PATTERNS = {
    # ── HTTP responses ───────────────────────────────────────────────────────
    # Rails: "Completed 200 OK in 142ms"
    "latency":     r"Completed \d+ .* in (?P<duration>\d+)ms",

    # ── Hard errors ──────────────────────────────────────────────────────────
    "error":       r"(ERROR|FATAL): (?P<message>.*)",

    # ── ActiveRecord queries with timing ─────────────────────────────────────
    # Rails: "Account Load (531.5ms)  SELECT ..."
    # Must come BEFORE the bare `query` pattern — more specific.
    "db_query":    r"(?P<table>\w+) (?:Load|Update|Create|Destroy|Exists\?|Count|Pluck)"
                   r" \((?P<duration>\d+(?:\.\d+)?)ms\)",

    # Bare SQL SELECT (catches queries not prefixed by AR model name)
    "query":       r"SELECT .* FROM (?P<table>\w+)",

    # ── Eager loading (Bullet gem) ────────────────────────────────────────────
    # "AVOID eager loading detected"
    # "  Contact => [:kula_ats_applications]"
    "eager_load":  r"AVOID eager loading detected"
                   r"|\s+(?P<table>\w+) => \[(?P<message>[^\]]*)\]",

    # ── Framework / library warnings ─────────────────────────────────────────
    # Rails: "DEPRECATION WARNING: ..."
    "deprecation": r"DEPRECATION WARNING[:\s]+(?P<message>.{0,200})",

    # Generic !! warnings from gems: "!!! RubyLLM's legacy acts_as API ..."
    "warning":     r"!!!\s+(?P<message>.+)",
}
