import logging
import sys
from typing import Any, Dict


class StructuredFormatter(logging.Formatter):
    """Custom logging formatter outputting clean, readable, structured logs."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return (
            f"[{log_data['timestamp']}] [{log_data['level']}] "
            f"[{log_data['logger']}]: {log_data['message']}"
            + (f"\n{log_data['exception']}" if "exception" in log_data else "")
        )


def setup_logging(debug: bool = False) -> logging.Logger:
    """Configure root and application loggers."""
    log_level = logging.DEBUG if debug else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        StructuredFormatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers = [handler]

    # Suppress verbose botocore logs
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("aioboto3").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    logger = logging.getLogger("cloud_storage")
    logger.setLevel(log_level)
    return logger


logger = setup_logging()

