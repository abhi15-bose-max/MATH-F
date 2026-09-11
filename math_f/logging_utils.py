"""Structured logging setup shared by the CLI commands.

Format matches the plain `[LEVEL] message` style requested by the spec so
overnight console/log output stays easy to scan, e.g.:

    [INFO] Experiment started
    [INFO] Task 1/244
    [INFO] Attempt 1 -> FAIL
    [CRITICAL] MALFORMED CANDIDATE
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


class _PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return f"[{record.levelname}] {record.getMessage()}"


def setup_logging(log_file: Optional[Path] = None, name: str = "math_f") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(_PlainFormatter())
    logger.addHandler(stream_handler)

    if log_file is not None:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(_PlainFormatter())
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "math_f") -> logging.Logger:
    return logging.getLogger(name)
