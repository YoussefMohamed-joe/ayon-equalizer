"""AYON-style plate base name and renaming for undistorted plate representation."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

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
    log,
) -> list[str]:
    """Rename frame.*.exr to plate_base_name.NNNN.exr in place. Returns new filenames."""
    time.sleep(1.5)
    frame_files = sorted(undistorted_dir.glob("frame.*.exr"))
    out = []
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
                    new_name = f.name
            out.append(new_name)
        else:
            out.append(f.name)
    return out
