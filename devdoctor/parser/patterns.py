"""Built-in regex patterns for log parsing.

Patterns are tried in order — first match wins.
All patterns should use named capture groups so the engine can populate
the normalised event fields (message, duration, table).
"""

DEFAULT_PATTERNS = {
    # ── OOM: before generic error ─────────────────────────────────────────────
    # Must precede `error` because Node OOM begins with "FATAL ERROR: ..."
    # Node.js:  "FATAL ERROR: Reached heap limit ... JavaScript heap out of memory"
    # Java:     "java.lang.OutOfMemoryError: Java heap space"
    # Go:       "runtime: out of memory: cannot allocate ..."
    "oom":          r"JavaScript heap out of memory|OutOfMemoryError|runtime: out of memory",

    # ── Application panics / crashes ──────────────────────────────────────────
    # Go:   "panic: runtime error: index out of range [3] with length 3"
    # Go:   "fatal error: concurrent map read and map write"
    # Node: "Uncaught TypeError: Cannot read properties of undefined"
    "panic":        r"(?:panic|fatal error|Uncaught\s+\w*Error)[:\s]+(?P<message>.+)",

    # ── Unhandled promise rejections (Node.js) ─────────────────────────────────
    # Must precede `connection` — the rejection message may itself contain
    # "connection refused", which would match the connection pattern first.
    # Node <15: "UnhandledPromiseRejectionWarning: Error: connection refused"
    # Node 15+: "UnhandledPromiseRejection: This error originated ..."
    "unhandled":    r"UnhandledPromise(?:RejectionWarning|Rejection)[:\s]+(?P<message>.*)",

    # ── HTTP / request latency ─────────────────────────────────────────────────

    # Rails:         "Completed 200 OK in 142ms"
    "latency":      r"Completed \d{3} .* in (?P<duration>\d+)ms",

    # Express/Morgan "GET /api/users 200 142.123 ms - 512"
    # (morgan 'dev' and 'tiny' formats both use this layout)
    "latency_http": r"(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) \S+ \d{3} (?P<duration>\d+(?:\.\d+)?) ms",

    # Gin (Go):      "[GIN] 2024/01/01 - 14:00:00 | 200 |   3.123ms |  127.0.0.1 | GET  /path"
    "latency_gin":  r"\[GIN\].*\|\s*(?P<duration>\d+(?:\.\d+)?)ms\s*\|",

    # ── Hard errors ───────────────────────────────────────────────────────────
    # Rails / Python logging / Go structured logs / Java Log4j
    "error":        r"(?:ERROR|FATAL|CRITICAL)[:\s]+(?P<message>.*)",

    # ── Timeouts / deadline exceeded ──────────────────────────────────────────
    # Go:      "context deadline exceeded", "context canceled"
    # Node:    "connect ETIMEDOUT"
    # Go HTTP: "net/http: request canceled (Client.Timeout exceeded)"
    # General: "timed out", "i/o timeout"
    "timeout":      r"context deadline exceeded"
                    r"|context canceled"
                    r"|ETIMEDOUT"
                    r"|timed?\s*out"
                    r"|i/o timeout"
                    r"|Client\.Timeout exceeded",

    # ── Connection errors ──────────────────────────────────────────────────────
    # Node error codes: ECONNREFUSED / ECONNRESET / EADDRINUSE
    # Go:              "dial tcp 127.0.0.1:5432: connect: connection refused"
    # General:         "connection refused", "connection reset by peer"
    "connection":   r"ECONNREFUSED"
                    r"|ECONNRESET"
                    r"|EADDRINUSE"
                    r"|connection refused"
                    r"|connection reset by peer"
                    r"|dial tcp .+: connect: connection refused",

    # ── Concurrency / race conditions / deadlocks ──────────────────────────────
    # Go -race flag:    "WARNING: DATA RACE"
    # Go runtime:       "all goroutines are asleep - deadlock!"
    # PostgreSQL/MySQL: "deadlock detected", "Deadlock found when trying to get lock"
    "concurrency":  r"DATA RACE"
                    r"|goroutines are asleep - deadlock"
                    r"|deadlock detected"
                    r"|Deadlock found when trying to get lock",

    # ── Stack overflow ─────────────────────────────────────────────────────────
    # Node/V8:  "RangeError: Maximum call stack size exceeded"
    # Java:     "java.lang.StackOverflowError"
    # Go:       "runtime: goroutine stack exceeds 1000000000-byte limit"
    "stackoverflow": r"Maximum call stack size exceeded"
                     r"|StackOverflowError"
                     r"|goroutine stack exceeds",

    # ── Python exceptions ──────────────────────────────────────────────────────
    # Standalone line at the start of every Python traceback block
    "traceback":    r"Traceback \(most recent call last\)",

    # ── ActiveRecord queries with timing ──────────────────────────────────────
    # Rails: "Account Load (531.5ms)  SELECT ..."
    # Must come BEFORE the bare `query` pattern — more specific.
    "db_query":     r"(?P<table>\w+) (?:Load|Update|Create|Destroy|Exists\?|Count|Pluck)"
                    r" \((?P<duration>\d+(?:\.\d+)?)ms\)",

    # ── Bare SQL SELECT (catches queries not prefixed by AR model name) ────────
    "query":        r"SELECT .* FROM (?P<table>\w+)",

    # ── N+1 / eager loading (Bullet gem) ─────────────────────────────────────
    # "AVOID eager loading detected"
    # "  Contact => [:kula_ats_applications]"
    "eager_load":   r"AVOID eager loading detected"
                    r"|\s+(?P<table>\w+) => \[(?P<message>[^\]]*)\]",

    # ── Framework / library warnings ──────────────────────────────────────────
    # Rails: "DEPRECATION WARNING: ..."
    "deprecation":  r"DEPRECATION WARNING[:\s]+(?P<message>.{0,200})",

    # Generic gem / library warnings: "!!! RubyLLM's legacy acts_as API ..."
    "warning":      r"!!!\s+(?P<message>.+)",
}
