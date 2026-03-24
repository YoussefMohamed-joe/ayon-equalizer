"""Overscan utilities for 3DEqualizer.

This module centralizes all overscan-related math so other plugins
(`create_matchmove`, publisher button, distorted-plate extractor) can just call
simple helpers instead of inlining tde4/importlib logic.
"""

from __future__ import annotations


class OverscanError(Exception):
    """Raised when overscan cannot be computed from the current 3DE context."""


def compute_overscan_percent(camera) -> tuple[float, float]:
    """Compute overscan width/height % for a given 3DE camera.

    Uses 3DE's built-in ``calc_overscan_distortion_bbox.py`` script.
    Use this when you have a specific camera (e.g. from instance creator_attributes).

    Returns:
        (width_pct, height_pct)

    Raises:
        OverscanError: When anything needed for the calculation is missing.
    """
    import os
    import sys
    import importlib.util

    try:
        import tde4
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise OverscanError(f"tde4 module is not available: {exc!r}") from exc

    if camera is None:
        raise OverscanError("Camera is None.")

    try:
        root = tde4.get3DEInstallPath()
        scripts_dir = os.path.join(root, "sys_data", "py_scripts") if root else None
    except Exception as exc:  # pragma: no cover - defensive
        raise OverscanError(f"get3DEInstallPath() failed: {exc!r}") from exc

    if not scripts_dir or not os.path.isdir(scripts_dir):
        raise OverscanError(
            "3DE script path not found (sys_data/py_scripts) from get3DEInstallPath()."
        )

    calc_path = os.path.join(scripts_dir, "calc_overscan_distortion_bbox.py")
    if not os.path.isfile(calc_path):
        raise OverscanError(f"Script not found: {calc_path}")

    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        spec = importlib.util.spec_from_file_location(
            "calc_overscan_distortion_bbox", calc_path
        )
        calc_mod = importlib.util.module_from_spec(spec)
        calc_mod.tde4 = tde4
        spec.loader.exec_module(calc_mod)
    except Exception as exc:
        raise OverscanError(
            f"Failed to load calc_overscan_distortion_bbox.py: {exc!r}"
        ) from exc

    try:
        bbox = calc_mod.bbdld_compute_bounding_box(camera)
    except Exception as exc:
        raise OverscanError(
            f"bbdld_compute_bounding_box(cam) failed: {exc!r}"
        ) from exc

    w_nonsymm = float(bbox[2])
    h_nonsymm = float(bbox[3])
    w_orig = tde4.getCameraImageWidth(camera)
    h_orig = tde4.getCameraImageHeight(camera)
    if not w_orig or not h_orig:
        raise OverscanError("Camera image width/height are zero.")

    # User-facing overscan percent is defined as:
    #   overscan_resolution / main_resolution * 100
    # so 100% means no overscan, >100% means bigger overscan plate.
    w_pct = round((w_nonsymm / w_orig) * 100.0, 4)
    h_pct = round((h_nonsymm / h_orig) * 100.0, 4)
    return w_pct, h_pct


def compute_overscan_percent_from_current_camera() -> tuple[float, float]:
    """Compute overscan width/height % from current 3DE camera.

    Convenience wrapper: gets tde4.getCurrentCamera() and calls
    compute_overscan_percent(cam).
    """
    try:
        import tde4
    except ImportError as exc:
        raise OverscanError(f"tde4 module is not available: {exc!r}") from exc

    cam = tde4.getCurrentCamera()
    if cam is None:
        raise OverscanError("tde4.getCurrentCamera() returned None.")
    return compute_overscan_percent(cam)


def bbdld_compute_bounding_box(camera):
    """Backward-compatible helper used by distorted-plate extractor.

    Uses :func:`compute_overscan_percent` for the given camera and returns
    (x_min, y_min, width, height) in pixels.
    """
    try:
        import tde4
    except ImportError as exc:  # pragma: no cover
        raise OverscanError(f"tde4 module is not available: {exc!r}") from exc

    w_pct, h_pct = compute_overscan_percent(camera)
    w_orig = tde4.getCameraImageWidth(camera)
    h_orig = tde4.getCameraImageHeight(camera)
    # overscan_pct = overscan/main * 100, so overscan_px = pct/100 * main
    width = (w_pct / 100.0) * w_orig
    height = (h_pct / 100.0) * h_orig
    return (0.0, 0.0, width, height)


# Plugin name under which publish form stores overscan attributes
_MATCHMOVE_PUBLISH_PLUGIN = "ExtractMatchmoveScriptMaya"


def inject_matchmove_overscan(instance_data: dict) -> None:
    """Fill overscan width/height on instance_data from the selected camera.

    Mutates instance_data in place: sets attribute_values and
    publish_attributes[ExtractMatchmoveScriptMaya] with overscan_percent_width
    and overscan_percent_height. No-op on failure (e.g. no camera).
    """
    try:
        import tde4
    except ImportError:
        return

    creator_attrs = instance_data.get("creator_attributes") or {}
    cam_sel = creator_attrs.get("camera_selection", "__current__")
    if cam_sel in ("__current__", "__all__", "__ref__", "__seq__"):
        cam = tde4.getCurrentCamera()
    else:
        cam = cam_sel

    if cam is None:
        return
    try:
        w_pct, h_pct = compute_overscan_percent(cam)
    except (OverscanError, Exception):
        return

    attrs = instance_data.get("attribute_values") or {}
    attrs = dict(attrs)
    attrs["overscan_percent_width"] = w_pct
    attrs["overscan_percent_height"] = h_pct
    instance_data["attribute_values"] = attrs

    pub = instance_data.get("publish_attributes") or {}
    pub = dict(pub)
    plugin_attrs = dict(pub.get(_MATCHMOVE_PUBLISH_PLUGIN) or {})
    plugin_attrs["overscan_percent_width"] = w_pct
    plugin_attrs["overscan_percent_height"] = h_pct
    pub[_MATCHMOVE_PUBLISH_PLUGIN] = plugin_attrs
    instance_data["publish_attributes"] = pub

