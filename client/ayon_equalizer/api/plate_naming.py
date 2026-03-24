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
    ext: str,
    log: Any,
) -> list[str]:
    """Rename frame.*.<ext> to plate_base_name.NNNN.<ext> in place.

    Runs multiple passes until no frame.*.<ext> remain (Image Warp may still
    be writing when the first pass runs). Returns the list of final filenames
    by globbing plate_base_name.*.<ext> so the representation matches disk
    and AYON sees a single sequence.

    Args:
        ext: File extension without dot (e.g. "jpg" or "exr").

    Returns:
        List of new filenames (e.g. pip_sq01_matchmoveMain_v014.1001.jpg).
    """
    ext_lower = ext.lower()
    pattern = re.compile(r"frame\.(\d+)\.%s$" % re.escape(ext_lower), re.IGNORECASE)
    
    max_retries = 30
    retry_delay = 0.5
    
    frame_files = sorted(undistorted_dir.glob(f"frame.*.{ext_lower}"))
    for f in frame_files:
        m = pattern.match(f.name)
        if not m:
            continue
            
        new_name = f"{plate_base_name}.{m.group(1)}.{ext_lower}"
        new_path = f.parent / new_name
        
        if new_path == f:
            continue
            
        success = False
        last_error = None
        for attempt in range(max_retries):
            try:
                f.rename(new_path)
                success = True
                break
            except OSError as e:
                last_error = e
                time.sleep(retry_delay)
                
        if not success:
            log.warning("Could not rename %s to %s after %d retries: %s", f.name, new_name, max_retries, last_error)

    # Build list from disk so we only report one pattern (no mixed frame.* + plate.*)
    out = sorted(
        f.name for f in undistorted_dir.glob(f"{plate_base_name}.*.{ext_lower}")
    )
    return out
