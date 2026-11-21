"""DEVELOPMENT templates. Written separately from test_templates.py; shares no topology, vocabulary
or component name with it. Used for prompt work and pilot calibration only."""
from ..schemas import Split, Stratum
from .engine import SILENT_FAULT, Family, Topology, Vocab

DEV_SHOP = Topology(
    id="dev-shop", entry="storefront",
    edges={"storefront": ("cart-svc", "session-svc"), "cart-svc": ("pricing-svc",),
           "pricing-svc": ("inventory-db",), "session-svc": ("session-cache",)},
    ports={"cart-svc": 8101, "session-svc": 8102, "pricing-svc": 8103, "inventory-db": 5432,
           "session-cache": 6379},
    extras=("metrics-agent", "mailer"))

DEV_LEDGER = Topology(
    id="dev-ledger", entry="api-edge",
    edges={"api-edge": ("ledger-svc", "authz-svc"), "ledger-svc": ("posting-svc",),
           "posting-svc": ("journal-db",), "authz-svc": ("authz-db",)},
    ports={"ledger-svc": 9001, "authz-svc": 9002, "posting-svc": 9003, "journal-db": 3306, "authz-db": 3307},
    extras=("audit-shipper", "cron-runner"))

DV_JAVA = Vocab(
    id="dv-java", ts_style="iso_z",
    levels={"INFO": "INFO", "WARN": "WARN", "ERROR": "ERROR", "FATAL": "FATAL"},
    ok=("request completed in {ms}ms status=200 rid={rid}", "health check passed in {ms}ms"),
    benign_warn=("GC pause {ms}ms (young gen)", "slow request {ms}0ms rid={rid}"),
    dep_errors=("java.net.ConnectException: Connection refused to {dep}:{port} rid={rid}",
                "call to {dep} failed: HTTP 503 rid={rid}"),
    retry="retrying call to {dep} (attempt 2/3)",
    gave_up="giving up on {dep} after 3 attempts",
    entry_5xx=("returned 503 to client: dependency {dep} failed rid={rid}",
               "HTTP 502 Bad Gateway from {dep} rid={rid}"),
    timeout=("java.net.SocketTimeoutException: read timed out after 5000ms calling {dep} rid={rid}",),
    distractors=(("ERROR", "certificate rotation job failed for internal CA (will retry)"),
                 ("WARN", "thread pool saturation 90% on worker group"),
                 ("ERROR", "failed to send weekly report email: SMTP 421")),
    flood_warn=("metrics push delayed {ms}ms (buffer 80%)", "queue lag {n} messages on topic events"),
    faults={
        "disk_full": ((-50, "WARN", "disk usage {pct}% on /var/lib/data"),
                      (0, "ERROR", "java.io.IOException: No space left on device"),
                      (3, "FATAL", "storage engine halted: cannot write WAL")),
        "oom": ((-40, "WARN", "heap usage {pct}% after full GC"),
                (0, "ERROR", "java.lang.OutOfMemoryError: Java heap space"),
                (2, "FATAL", "JVM terminated by OOM killer")),
        "bad_config": ((-4, "INFO", "reloading configuration from /etc/app/app.yaml"),
                       (0, "ERROR", "invalid configuration: max_connections=-1"),
                       (2, "FATAL", "failed to apply configuration, shutting down")),
        "conn_pool_exhausted": ((-30, "WARN", "connection pool usage {pct}% (active={n})"),
                                (0, "ERROR", "HikariPool: connection is not available, request timed out"),
                                (5, "ERROR", "rejecting requests: connection pool exhausted")),
    })

DV_GO = Vocab(
    id="dv-go", ts_style="space_ms",
    levels={"INFO": "INFO", "WARN": "WARNING", "ERROR": "ERROR", "FATAL": "FATAL"},
    ok=("handled request rid={rid} status=200 dur={ms}ms", "ping ok latency={ms}ms"),
    benign_warn=("slow handler rid={rid} dur={ms}0ms", "retry budget low on client pool"),
    dep_errors=("dial tcp {dep}:{port}: connect: connection refused rid={rid}",
                "rpc error: code = Unavailable desc = {dep} unavailable rid={rid}"),
    retry="backoff before retrying {dep} (2/3)",
    gave_up="request to {dep} failed permanently after retries",
    entry_5xx=("responding 503: upstream {dep} error rid={rid}", "upstream {dep} returned 500 rid={rid}"),
    timeout=("context deadline exceeded calling {dep} rid={rid}",),
    distractors=(("ERROR", "leader election lost for cron lock, re-electing"),
                 ("WARN", "clock drift 180ms detected vs NTP"),
                 ("ERROR", "failed to flush audit batch: broken pipe")),
    flood_warn=("export batch dropped {n} spans", "rate limiter near capacity ({pct}%)"),
    faults={
        "disk_full": ((-45, "WARN", "filesystem /data {pct}% full"),
                      (0, "ERROR", "write /data/wal/000123.log: no space left on device"),
                      (4, "FATAL", "panic: unable to persist write-ahead log")),
        "oom": ((-35, "WARN", "memory usage {pct}% of limit"),
                (0, "ERROR", "runtime: out of memory: cannot allocate 268435456-byte block"),
                (1, "FATAL", "fatal error: out of memory")),
        "bad_config": ((-3, "INFO", "loading config file config.toml"),
                       (0, "ERROR", "config: field pool_size must be > 0, got 0"),
                       (2, "FATAL", "exiting: invalid configuration")),
        "conn_pool_exhausted": ((-25, "WARN", "db pool wait count {n} rising"),
                                (0, "ERROR", "sql: database/sql: connection pool exhausted (max_open=50)"),
                                (6, "ERROR", "shedding load: no free database connections")),
    })

FAMILIES = (
    Family("df01", Split.DEV, DEV_SHOP, DV_JAVA, Stratum.EASY, "oom", "cart-svc"),
    Family("df02", Split.DEV, DEV_LEDGER, DV_GO, Stratum.MULTI_HOP, "disk_full", "journal-db"),
    Family("df03", Split.DEV, DEV_SHOP, DV_GO, Stratum.DISTRACTOR, "bad_config", "pricing-svc",
           distractor_components=("metrics-agent", "session-svc")),
    Family("df04", Split.DEV, DEV_LEDGER, DV_JAVA, Stratum.OVER_BUDGET, "conn_pool_exhausted", "posting-svc"),
    Family("df05", Split.DEV, DEV_SHOP, DV_JAVA, Stratum.CONCURRENT, "disk_full", "inventory-db",
           second_fault="oom", second_target="session-cache"),
    Family("df06", Split.DEV, DEV_LEDGER, DV_GO, Stratum.INSUFFICIENT, SILENT_FAULT, "posting-svc"),
)
