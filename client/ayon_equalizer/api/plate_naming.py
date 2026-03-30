"""Plate naming and renaming for undistorted plate representation."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    import pyblish.api


def get_plate_base_name(instance: "pyblish.api.Instance") -> str:
    """Build AYON-style base name, e.g. pip_sq01_matchmoveMain_v014."""
    ctx = instance.context
    project_name = (
        instance.data.get("projectName")
        or (ctx.data.get("projectName") if ctx else None)
        or "prj"
    )
    project_code = instance.data.get("projectCode") or project_name[:3].lower()
    folder_path = (
        instance.data.get("folderPath")
        or (ctx.data.get("folderPath") if ctx else None)
        or ""
    )
    folder_name = folder_path.split("/")[-1] if folder_path else "shot"
    product_name = (
        instance.data.get("productName")
        or instance.data.get("name")
        or "matchmoveMain"
    )
    version_num = instance.data.get("version", 1)
    return f"{project_code}_{folder_name}_{product_name}_v{version_num:03d}"


def rename_frames_to_ayon_style(
    undistorted_dir: Path,
    plate_base_name: str,
    ext: str,
    log: "logging.Logger",
) -> list[str]:
    """Rename frame.*.ext to plate_base_name.NNNN.ext, retrying on file locks."""
    ext_lower = ext.lower()
    pattern = re.compile(
        r"frame\.(\d+)\.%s$" % re.escape(ext_lower), re.IGNORECASE
    )

    max_retries = 30
    retry_delay = 0.5

    for f in sorted(undistorted_dir.glob(f"frame.*.{ext_lower}")):
        m = pattern.match(f.name)
        if not m:
            continue

        new_name = f"{plate_base_name}.{m.group(1)}.{ext_lower}"
        new_path = f.parent / new_name
        if new_path == f:
            continue

        last_error = None
        for _ in range(max_retries):
            try:
                f.rename(new_path)
                break
            except OSError as e:
                last_error = e
                time.sleep(retry_delay)
        else:
            log.warning(
                "Could not rename %s to %s after %d retries: %s",
                f.name, new_name, max_retries, last_error,
            )

    return sorted(
        f.name
        for f in undistorted_dir.glob(f"{plate_base_name}.*.{ext_lower}")
    )
