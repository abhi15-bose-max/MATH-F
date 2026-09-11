"""Best-effort git provenance lookup. Never raises."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


def current_git_commit(repo_dir: Optional[str] = None) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir or Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def is_git_dirty(repo_dir: Optional[str] = None) -> Optional[bool]:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir or Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return bool(out.stdout.strip())
    except Exception:
        pass
    return None
