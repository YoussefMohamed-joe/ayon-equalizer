"""Resolve full publish path for matchmove so scripts can reference plates by full path."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import pyblish.api


def get_matchmove_publish_dir(instance: "pyblish.api.Instance") -> Optional[str]:
    """Full path to the matchmove version folder where AYON publishes (e.g. .../matchmoveMain/v014)."""
    project_root = None
    ctx = instance.context
    project_name = instance.data.get("projectName") or (ctx.data.get("projectName") if ctx else None) or ""
    folder_path = (
        instance.data.get("folderPath") or (ctx.data.get("folderPath") if ctx else None) or ""
    ).replace("/", os.sep).strip(os.sep)
    product_name = instance.data.get("productName") or instance.data.get("name") or "matchmoveMain"
    version = instance.data.get("version", 1)

    for mod in ("ayon_core.pipeline", "ayon_core.client"):
        try:
            import importlib
            m = importlib.import_module(mod)
            get_roots = getattr(m, "get_project_roots", None)
            if get_roots and project_name:
                roots = get_roots(project_name)
                if roots:
                    project_root = roots.get("publish") or roots.get("work") or ""
                    if project_root:
                        break
        except Exception:
            continue

    if not project_root and ctx:
        current_file = (ctx.data.get("currentFile") or "").replace("\\", "/")
        if "/projects/" in current_file:
            prefix = current_file.split("/projects/")[0]
            after = current_file.split("/projects/", 1)[-1]
            parts = [p for p in after.split("/") if p]
            if parts:
                project_root = f"{prefix}/projects/{parts[0]}"
                if not folder_path and len(parts) >= 3:
                    folder_path = f"{parts[1]}/{parts[2]}"

    if not project_root and ctx:
        project_root = ctx.data.get("projectRoot") or ctx.data.get("workDir") or ""
    if not project_root:
        project_root = instance.data.get("projectRoot") or instance.data.get("workDir") or ""
    if not project_root:
        project_root = os.environ.get("AYON_PROJECT_ROOT") or os.environ.get("PROJECT_ROOT") or ""

    if not project_root:
        return None
    project_root = project_root.rstrip(os.sep)
    if not folder_path:
        folder_path = "shots/sq01"
    full_dir = os.path.join(
        project_root,
        folder_path.replace("/", os.sep),
        "publish",
        "matchmove",
        product_name,
        f"v{version:03d}",
    )
    return os.path.normpath(full_dir)
