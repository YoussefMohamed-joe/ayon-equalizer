"""Set context projectRoot and folderPath from current workfile path."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pyblish.api


def set_project_root_from_path(
    context: "pyblish.api.Context",
    current_file: str,
) -> None:
    """Set context.data projectRoot and folderPath when current_file is under .../projects/Name/..."""
    normalized = (current_file or "").replace("\\", "/")
    if "/projects/" not in normalized:
        return
    prefix = normalized.split("/projects/")[0]
    after = normalized.split("/projects/", 1)[-1]
    parts = [p for p in after.split("/") if p]
    if not parts:
        return
    context.data["projectRoot"] = f"{prefix}/projects/{parts[0]}".replace(
        "/", "\\" if "\\" in current_file else "/"
    )
    if len(parts) >= 3:
        context.data["folderPath"] = f"{parts[1]}/{parts[2]}"
