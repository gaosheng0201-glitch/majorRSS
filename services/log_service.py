"""
Central logging setup for MajorRSS.

Everything in the pipeline used to go through bare print(); in the packaged
sidecar stdout is piped to the Tauri console and nothing survives on disk.
This module writes a rotating log file into the app data directory (next to
the SQLite DB) and keeps a console handler that never crashes on GBK/emoji
encoding issues (Windows consoles).
"""
import io
import logging
import logging.handlers
import os
import sys

_configured = False


def get_log_dir() -> str:
    from db.config import get_app_data_dir
    log_dir = os.path.join(get_app_data_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def get_log_path() -> str:
    return os.path.join(get_log_dir(), "majorss.log")


class _SafeStreamHandler(logging.StreamHandler):
    """Console handler tolerant of non-UTF8 terminals (Windows GBK + emoji)."""

    def emit(self, record):
        try:
            super().emit(record)
        except UnicodeEncodeError:
            try:
                msg = self.format(record)
                encoding = getattr(self.stream, "encoding", None) or "ascii"
                self.stream.write(msg.encode(encoding, errors="replace").decode(encoding) + self.terminator)
                self.flush()
            except Exception:
                pass
        except Exception:
            self.handleError(record)


def setup_logging(level: int = logging.INFO):
    """Idempotent. Safe to call from FastAPI lifespan and standalone workers."""
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            get_log_path(), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except Exception as e:
        # A read-only disk must not prevent the app from starting.
        print(f"[log_service] Failed to attach file handler: {e}")

    console = _SafeStreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    # APScheduler warnings ("maximum instances reached", job crashes) were
    # previously lost to an unconfigured logger; keep them visible.
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    # uvicorn access logs are noisy in the log file; warnings only.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def tail_log(lines: int = 200) -> str:
    """Return the last N lines of the current log file."""
    path = get_log_path()
    if not os.path.exists(path):
        return ""
    lines = max(1, min(lines, 2000))
    try:
        with open(path, "rb") as f:
            f.seek(0, io.SEEK_END)
            size = f.tell()
            # Read up to ~512KB from the end; plenty for 2000 lines.
            read_size = min(size, 512 * 1024)
            f.seek(size - read_size)
            data = f.read().decode("utf-8", errors="replace")
        return "\n".join(data.splitlines()[-lines:])
    except Exception as e:
        return f"[log_service] Failed to read log file: {e}"
