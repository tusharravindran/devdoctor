"""Built-in regex patterns for log parsing."""

DEFAULT_PATTERNS = {
    "latency": r"Completed \d+ .* in (?P<duration>\d+)ms",
    "error": r"(ERROR|FATAL): (?P<message>.*)",
    "query": r"SELECT .* FROM (?P<table>\w+)",
}
