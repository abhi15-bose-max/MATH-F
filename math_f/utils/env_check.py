"""Environment introspection used for provenance metadata and `smoke-test`.

Every function here is best-effort and never raises: an unavailable tool or
package is reported as such rather than crashing the caller. This module is
intentionally free of hard dependencies on torch/transformers/lean so it can
be imported anywhere (including in unit tests) without those tools present.
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def python_info() -> dict:
    return {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
    }


def torch_info() -> dict:
    try:
        import torch  # type: ignore
    except ImportError:
        return {"available": False}
    info = {"available": True, "version": torch.__version__}
    try:
        info["cuda_available"] = bool(torch.cuda.is_available())
        if info["cuda_available"]:
            info["cuda_version"] = getattr(torch.version, "cuda", None)
            info["gpu_count"] = torch.cuda.device_count()
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["bf16_supported"] = bool(torch.cuda.is_bf16_supported())
    except Exception as e:  # pragma: no cover - defensive
        info["cuda_error"] = str(e)
    return info


def transformers_info() -> dict:
    try:
        import transformers  # type: ignore
    except ImportError:
        return {"available": False}
    return {"available": True, "version": transformers.__version__}


def datasets_info() -> dict:
    try:
        import datasets  # type: ignore
    except ImportError:
        return {"available": False}
    return {"available": True, "version": datasets.__version__}


def lean_executable_path(lean_cmd: Optional[list] = None) -> Optional[str]:
    exe = (lean_cmd or ["lake"])[0]
    return shutil.which(exe)


def lean_version(lean_project_dir: str = ".", lean_cmd: Optional[list] = None) -> dict:
    lean_cmd = lean_cmd or ["lake", "env", "lean"]
    exe_path = lean_executable_path(lean_cmd)
    if exe_path is None:
        return {"available": False, "reason": f"'{lean_cmd[0]}' not found on PATH"}
    try:
        out = subprocess.run(
            lean_cmd + ["--version"],
            cwd=lean_project_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if out.returncode == 0:
            return {"available": True, "version": out.stdout.strip() or out.stderr.strip()}
        return {
            "available": False,
            "reason": f"exit code {out.returncode}",
            "stderr": out.stderr.strip(),
        }
    except FileNotFoundError as e:
        return {"available": False, "reason": str(e)}
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "timed out running --version"}
    except Exception as e:  # pragma: no cover - defensive
        return {"available": False, "reason": str(e)}


def mathlib_info(lean_project_dir: str = ".") -> dict:
    """Best-effort Mathlib revision lookup from a lake-manifest.json."""
    manifest_path = Path(lean_project_dir) / "lake-manifest.json"
    if not manifest_path.exists():
        return {"available": False, "reason": "lake-manifest.json not found"}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for pkg in data.get("packages", []):
            if pkg.get("name", "").lower() == "mathlib":
                return {
                    "available": True,
                    "rev": pkg.get("rev"),
                    "git_url": pkg.get("url") or pkg.get("git"),
                }
        return {"available": False, "reason": "mathlib entry not found in manifest"}
    except Exception as e:  # pragma: no cover - defensive
        return {"available": False, "reason": str(e)}


def full_environment_report(config) -> dict:
    from math_f.utils.git_info import current_git_commit, is_git_dirty

    return {
        "python": python_info(),
        "torch": torch_info(),
        "transformers": transformers_info(),
        "datasets": datasets_info(),
        "lean": lean_version(
            config.verification.lean_project_dir, config.verification.lean_cmd
        ),
        "mathlib": mathlib_info(config.verification.lean_project_dir),
        "model_name": config.model.name,
        "model_revision": config.model.revision,
        "model_backend": config.model.backend,
        "dataset_name": config.evaluation.dataset_name,
        "dataset_split": config.evaluation.split,
        "random_seed": config.evaluation.random_seed,
        "git_commit": current_git_commit(),
        "git_dirty": is_git_dirty(),
    }
