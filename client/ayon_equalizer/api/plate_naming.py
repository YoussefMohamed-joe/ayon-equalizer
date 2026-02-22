"""AYON-style plate base name and renaming for undistorted plate representation."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pyblish.api


def get_plate_base_name(instance: "pyblish.api.Instance") -> str:
    """Build AYON-style base name e.g. pip_sq01_matchmoveMain_v014."""
    ctx = instance.context
    project_name = instance.data.get("projectName") or (ctx.data.get("projectName") if ctx else None) or "prj"
    project_code = instance.data.get("projectCode") or project_name[:3].lower()
    folder_path = instance.data.get("folderPath") or (ctx.data.get("folderPath") if ctx else None) or ""
    folder_name = folder_path.split("/")[-1] if folder_path else "shot"
    product_name = instance.data.get("productName") or instance.data.get("name") or "matchmoveMain"
    version_num = instance.data.get("version", 1)
    return f"{project_code}_{folder_name}_{product_name}_v{version_num:03d}"


def rename_frames_to_ayon_style(
    undistorted_dir: Path,
    plate_base_name: str,
    log: Any,
) -> list[str]:
    """Rename frame.*.exr to plate_base_name.NNNN.exr in place.

    Runs multiple passes until no frame.*.exr remain (Image Warp may still
    be writing when the first pass runs). Returns the list of final filenames
    by globbing plate_base_name.*.exr so the representation matches disk
    and AYON sees a single sequence.

    Returns:
        List of new filenames (e.g. pip_sq01_matchmoveMain_v014.1001.exr).
    """
    time.sleep(1.5)
    max_passes = 5
    for _ in range(max_passes):
        frame_files = sorted(undistorted_dir.glob("frame.*.exr"))
        if not frame_files:
            break
        for f in frame_files:
            m = re.match(r"frame\.(\d+)\.exr$", f.name, re.IGNORECASE)
            if m:
                new_name = f"{plate_base_name}.{m.group(1)}.exr"
                new_path = f.parent / new_name
                if new_path != f:
                    try:
                        f.rename(new_path)
                    except OSError as e:
                        log.warning("Could not rename %s to %s: %s", f.name, new_name, e)
        time.sleep(0.5)
    # Build list from disk so we only report one pattern (no mixed frame.* + plate.*)
    out = sorted(f.name for f in undistorted_dir.glob(f"{plate_base_name}.*.exr"))
    return out
