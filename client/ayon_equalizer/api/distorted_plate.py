"""Run 3DE Image Warp and add undistorted_plate representation.

Uses sdv_image_warp_gui's callback_run (same as GUI) so the
warp runs inside 3DE instead of driving the binary directly.
"""
from __future__ import annotations

import glob
import importlib.util
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import tde4

if TYPE_CHECKING:
    import logging

    import pyblish.api

from ayon_core.pipeline import KnownPublishError

from ayon_equalizer.api.overscan import bbdld_compute_bounding_box
from ayon_equalizer.api.plate_naming import (
    get_plate_base_name,
    rename_frames_to_ayon_style,
)

_image_warp_poll_state = None
IMAGE_WARP_POLL_TIMEOUT = 600
IMAGE_WARP_POLL_INTERVAL = 2
IMAGE_WARP_EXT = "jpg"
IMAGE_WARP_PATTERN = "frame.####.jpg"


def run_image_warp_and_add_representation(
    instance: "pyblish.api.Instance",
    staging_dir: str,
    tde4_path: Path,
    log: "logging.Logger",
) -> None:
    """Run Image Warp, rename frames, and add undistorted_plate representation."""
    staging_path = Path(staging_dir)
    undistorted_dir = staging_path / "undistorted_plate"
    undistorted_dir.mkdir(parents=True, exist_ok=True)

    enabled_cameras = [c for c in instance.data["cameras"] if c["enabled"]]
    if not enabled_cameras:
        raise KnownPublishError(
            "Distortion is enabled but no camera is selected."
        )
    first_cam = enabled_cameras[0]
    first_cam_id = first_cam["id"]
    camera_name = first_cam.get("name") or tde4.getCameraName(first_cam_id)
    output_path = str(undistorted_dir.resolve())

    log.info(
        "Image Warp: camera=%s, output=%s",
        camera_name,
        output_path,
    )

    attrs = instance.data.get("attribute_values") or {}
    try:
        overscan_width_pct = float(attrs.get("overscan_percent_width"))
        overscan_height_pct = float(attrs.get("overscan_percent_height"))
    except (TypeError, ValueError):
        overscan_width_pct = overscan_height_pct = None

    image_warp_error = None
    try:
        _run_image_warp(
            tde4_path,
            first_cam_id,
            output_path,
            log,
            overscan_width_pct,
            overscan_height_pct,
        )
        log.info("Image Warp finished.")
    except Exception as e:
        image_warp_error = e
        log.warning(
            "Could not run Image Warp automatically: %s. "
            "Export manually via Distortion Edit Controls -> Image Warp -> output: %s",
            e,
            undistorted_dir.as_posix(),
        )

    frame_files = sorted(undistorted_dir.glob(f"frame.*.{IMAGE_WARP_EXT}"))
    if not frame_files:
        msg = (
            "No undistorted frames rendered. "
            "Check camera frame range and image sequence path."
        )
        if image_warp_error is not None:
            msg += f" Image Warp error: {image_warp_error}"
        log.error(msg)
        return

    plate_base_name = get_plate_base_name(instance)
    frame_filenames = rename_frames_to_ayon_style(
        undistorted_dir, plate_base_name, IMAGE_WARP_EXT, log
    )

    instance.data["plate_base_name"] = plate_base_name
    instance.data["plate_ext"] = IMAGE_WARP_EXT

    if "representations" not in instance.data:
        instance.data["representations"] = []
    log.info(
        "Adding undistorted_plate representation: %d frame(s), %s.*.%s",
        len(frame_filenames),
        plate_base_name,
        IMAGE_WARP_EXT,
    )
    instance.data["representations"].append({
        "name": "undistorted_plate",
        "ext": IMAGE_WARP_EXT,
        "stagingDir": str(undistorted_dir),
        "files": frame_filenames,
        "data": {"ext": IMAGE_WARP_EXT},
        "colorspaceData": {"colorspace": "ACES - ACEScg"},
    })


def _run_image_warp(
    tde4_path: Path,
    camera_id: str,
    output_dir: str,
    log: "logging.Logger",
    overscan_width_pct: float | None = None,
    overscan_height_pct: float | None = None,
) -> None:
    """Run 3DE Image Warp via sdv_image_warp_gui callback_run."""
    global _image_warp_poll_state

    scripts_dir = tde4_path / "sys_data" / "py_scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    # Compute overscan pixels from percent or from distortion bbox
    if overscan_width_pct is not None and overscan_height_pct is not None:
        w_orig = tde4.getCameraImageWidth(camera_id) or 1
        h_orig = tde4.getCameraImageHeight(camera_id) or 1
        w_overscan_px = int((overscan_width_pct / 100.0) * w_orig)
        h_overscan_px = int((overscan_height_pct / 100.0) * h_orig)
    else:
        bbox = bbdld_compute_bounding_box(camera_id)
        w_overscan_px = int(bbox[2])
        h_overscan_px = int(bbox[3])

    log.debug(
        "Image Warp overscan: %d x %d px",
        w_overscan_px, h_overscan_px,
    )

    def noop_requester(*args, **kwargs):
        pass

    def question_ok(*args, **kwargs):
        return 1

    sys.modules["tde4"] = tde4

    warp_path = scripts_dir / "sdv_image_warp_gui.py"
    spec = importlib.util.spec_from_file_location(
        "sdv_image_warp_gui", warp_path.as_posix()
    )
    warp_script = importlib.util.module_from_spec(spec)
    warp_script.tde4 = tde4

    with patch("tde4.postCustomRequesterAndContinue", noop_requester), \
         patch("tde4.postQuestionRequester", question_ok):
        assert spec.loader is not None
        spec.loader.exec_module(warp_script)

    warp_instance = warp_script.the_warp_it_b_script
    warp_cls = type(warp_instance)
    warp_instance.list_item_userdata = 1

    t4o = warp_script.t4o
    t4o_cam = None
    for cam in t4o.camera.each():
        if cam.id() == camera_id:
            t4o_cam = cam
            break
    if t4o_cam is None:
        raise KnownPublishError("Could not resolve camera for Image Warp.")

    cam_entry = warp_cls.camera_entry(warp_instance, t4o_cam)
    cam_entry.list_item_position = 0
    margin_mode = 0
    cam_entry.set_overscan_x(margin_mode, w_overscan_px)
    cam_entry.set_overscan_y(margin_mode, h_overscan_px)
    cam_entry._crop_size_x = w_overscan_px
    cam_entry._crop_size_y = h_overscan_px

    _imgw_mod = __import__(
        "sdv_imgw_file_properties", fromlist=["imgw_enum"]
    )
    _imgw_mod.tde4 = tde4
    if hasattr(_imgw_mod, "__dict__"):
        _imgw_mod.__dict__["tde4"] = tde4
    imgw_enum = getattr(warp_script, "imgw_enum", _imgw_mod.imgw_enum)
    cam_entry.set_output_directory(
        imgw_enum.direction_undistort, output_dir,
    )
    cam_entry.set_output_file_pattern(
        imgw_enum.direction_undistort, IMAGE_WARP_PATTERN,
    )
    cam_entry.initialize_frameset()
    num_frames = getattr(cam_entry, "num_frames", 0) or 0
    if num_frames <= 0:
        raise KnownPublishError(
            "Camera has no frame range for Image Warp. "
            "Set the camera's playback or calculation range in 3DE."
        )
    cam_entry.name_of_camera = "cam_0"

    warp_instance._cameras = [cam_entry]
    warp_instance._num_frames_total = cam_entry.num_frames
    try:
        warp_instance.warp_it_num_cpus = tde4.getAvailableCPUCores()
    except Exception:
        warp_instance.warp_it_num_cpus = 1

    if not hasattr(warp_instance, "req") or warp_instance.req is None:
        warp_instance.req = 0

    class _PollState:
        is_running = True
        is_complete = False
        output_path = output_dir
        expected_frames = num_frames
        start_time = time.time()

    _image_warp_poll_state = _PollState()

    def _ayon_image_warp_poll():
        global _image_warp_poll_state
        if _image_warp_poll_state is None or not _image_warp_poll_state.is_running:
            return
        frames = glob.glob(
            os.path.join(_image_warp_poll_state.output_path, f"*.{IMAGE_WARP_EXT}")
        )
        if len(frames) >= _image_warp_poll_state.expected_frames:
            log.info("Image Warp complete: %d frames", len(frames))
            _image_warp_poll_state.is_complete = True
            _image_warp_poll_state.is_running = False
            tde4.setTimerCallbackFunction("", 0)
            return
        elapsed = time.time() - _image_warp_poll_state.start_time
        if elapsed > IMAGE_WARP_POLL_TIMEOUT:
            log.error("Image Warp timeout after %.0fs", elapsed)
            _image_warp_poll_state.is_running = False
            tde4.setTimerCallbackFunction("", 0)

    import __main__
    __main__._ayon_image_warp_poll = _ayon_image_warp_poll
    tde4.setTimerCallbackFunction("_ayon_image_warp_poll", 1000)

    log.info("Starting Image Warp (callback_run)...")
    try:
        warp_instance.callback_run(warp_instance.req, "w007", 0)
    except Exception as e:
        tde4.setTimerCallbackFunction("", 0)
        _image_warp_poll_state = None
        raise KnownPublishError(f"Image Warp failed to start: {e}") from e

    log.info("Waiting for Image Warp (polling every %ss)...", IMAGE_WARP_POLL_INTERVAL)
    start_poll = time.time()
    while _image_warp_poll_state.is_running:
        time.sleep(IMAGE_WARP_POLL_INTERVAL)
        frames = glob.glob(os.path.join(output_dir, f"*.{IMAGE_WARP_EXT}"))
        if len(frames) >= num_frames:
            log.info("Detected %d frames - warp complete", len(frames))
            break
        if time.time() - start_poll > IMAGE_WARP_POLL_TIMEOUT:
            tde4.setTimerCallbackFunction("", 0)
            _image_warp_poll_state = None
            raise KnownPublishError(
                f"Image Warp timeout - only {len(frames)}/{num_frames} frames"
            )

    tde4.setTimerCallbackFunction("", 0)
    _image_warp_poll_state = None

    final_frames = sorted(
        glob.glob(os.path.join(output_dir, f"*.{IMAGE_WARP_EXT}"))
    )
    if len(final_frames) < num_frames:
        raise KnownPublishError(
            f"Incomplete warp: {len(final_frames)}/{num_frames} frames"
        )
