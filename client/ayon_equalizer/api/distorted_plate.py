"""Image Warp (undistorted plate) for matchmove when Distortion is on.

Single place for running 3DE Image Warp and adding the undistorted_plate
representation. Uses sdv_image_warp_gui's callback_run (same as GUI) so the
warp runs inside 3DE instead of driving the binary directly.
"""
from __future__ import annotations

import glob
import importlib.util
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import tde4
from ayon_core.pipeline import KnownPublishError

from ayon_equalizer.api.overscan import bbdld_compute_bounding_box
from ayon_equalizer.api.plate_naming import get_plate_base_name, rename_frames_to_ayon_style

# State for timer callback (3DE looks up callback by name in __main__)
_image_warp_poll_state = None
IMAGE_WARP_POLL_TIMEOUT = 600
IMAGE_WARP_POLL_INTERVAL = 2


def run_image_warp_and_add_representation(
    instance,
    staging_dir: str,
    tde4_path: Path,
    log,
) -> None:
    """When Distortion is on: run Image Warp in the background and add representation.

    All of this runs during publish (no user interaction):
    - Uses the **selected camera** (first enabled camera from the instance).
    - Uses **overscan** from the camera's lens distortion (same as overscan % in the form).
    - Writes to **staging_dir/undistorted_plate**; Ayon then publishes from there to
      the version folder (custom or default publish path).

    instance: pyblish Instance with cameras data.
    staging_dir: staging directory (string); Ayon publishes from here.
    tde4_path: path to 3DE install (Path).
    log: logger for info/warnings.
    """
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
    camera_name = first_cam.get("name") or (tde4.getCameraName(first_cam_id) if first_cam_id else "?")

    # Output path: staging dir that Ayon will then publish to the version folder
    # Use absolute path so Image Warp subprocess writes to the right place
    output_path = str(undistorted_dir.resolve())

    # Optional forensic logging (some 3DE builds lack getCameraImage* APIs)
    if getattr(tde4, "getCameraImagePatternFilepath", None) and getattr(
        tde4, "getCameraImageFilepath", None
    ):
        try:
            current_cam = tde4.getCurrentCamera()
            current_frame = (
                tde4.getCurrentFrame(current_cam) if current_cam is not None else None
            )
            project_path = tde4.getProjectPath()
            image_pattern = tde4.getCameraImagePatternFilepath(first_cam_id)
            probe_frame = current_frame or tde4.getCameraFrameOffset(first_cam_id)
            probe_path = tde4.getCameraImageFilepath(first_cam_id, probe_frame)
            log.info("=== Image Warp ENV CHECK ===")
            log.info("Current camera: %s", current_cam)
            log.info("Current frame: %s", current_frame)
            log.info("Project path: %s", project_path)
            log.info("Working dir: %s", os.getcwd())
            log.info("TDE4_HOME: %s", os.getenv("TDE4_HOME"))
            log.info("Probe cam name: %s", camera_name)
            log.info("Probe image pattern: %s", image_pattern)
            log.info("Probe frame %s image: %s", probe_frame, probe_path)
            log.info("Probe input exists: %s", os.path.exists(probe_path))
        except Exception as env_exc:  # pragma: no cover - defensive
            log.warning("Image Warp env logging failed: %s", env_exc)

    os.makedirs(output_path, exist_ok=True)
    log.info(
        "Image Warp (background): camera=%s, output=%s (Ayon will publish from here)",
        camera_name,
        output_path,
    )
    image_warp_error = None
    try:
        _run_image_warp(tde4_path, first_cam_id, output_path, log)
        log.info("Image Warp finished.")
    except Exception as e:
        image_warp_error = e
        log.warning(
            "Could not run Image Warp automatically: %s. "
            "Export the undistorted plate manually: Distortion Edit "
            "Controls -> Image Warp -> set output to: %s",
            e,
            undistorted_dir.as_posix(),
        )

    # List actual frame files (Image Warp writes frame.####.exr)
    frame_files = sorted(undistorted_dir.glob("frame.*.exr"))
    if not frame_files:
        msg = (
            "No undistorted frames were rendered. Not adding undistorted_plate representation. "
            "Check: (1) Camera has a frame range (playback/calculation range in 3DE), "
            "(2) Camera has a valid image sequence path."
        )
        if image_warp_error is not None:
            msg += " Image Warp error: %s" % image_warp_error
        log.error(msg)
        return

    plate_base_name = get_plate_base_name(instance)
    frame_filenames = rename_frames_to_ayon_style(undistorted_dir, plate_base_name, log)

    if "representations" not in instance.data:
        instance.data["representations"] = []
    log.info(
        "Adding undistorted_plate representation with %d frame(s) to matchmove (%s.*.exr).",
        len(frame_filenames),
        plate_base_name,
    )
    instance.data["representations"].append({
        "name": "undistorted_plate",
        "ext": "exr",
        "stagingDir": str(undistorted_dir),
        "files": frame_filenames,
    })
    instance.data["plate_base_name"] = plate_base_name


def _run_image_warp(
    tde4_path: Path,
    camera_id,
    output_dir: str,
    log=None,
) -> None:
    """Run 3DE Image Warp via sdv_image_warp_gui callback_run (same as GUI).

    Uses tde4_objects camera, overscan from lens distortion bbox, and the given
    output_dir. Registers a timer callback and polls until frames are written
    or timeout. Does not drive the binary directly.
    """
    global _image_warp_poll_state

    scripts_dir = tde4_path / "sys_data" / "py_scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    # Overscan from lens distortion (same as overscan % in the form)
    bbox = bbdld_compute_bounding_box(camera_id)
    w_overscan_px = int(bbox[2])
    h_overscan_px = int(bbox[3])
    if log:
        w_orig = tde4.getCameraImageWidth(camera_id) or 1
        h_orig = tde4.getCameraImageHeight(camera_id) or 1
        w_pct = round(100.0 * w_overscan_px / w_orig, 2)
        h_pct = round(100.0 * h_overscan_px / h_orig, 2)
        log.debug(
            "Image Warp overscan: %d x %d px (%.2f%% x %.2f%%)",
            w_overscan_px, h_overscan_px, w_pct, h_pct,
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
        imgw_enum.direction_undistort, "frame.####.exr",
    )
    cam_entry.initialize_frameset()
    num_frames = getattr(cam_entry, "num_frames", 0) or 0
    if num_frames <= 0:
        raise KnownPublishError(
            "Camera has no frame range for Image Warp. "
            "In 3DE, set the camera's playback range or calculation range so at least one frame is exported."
        )
    cam_entry.name_of_camera = "cam_0"

    warp_instance._cameras = [cam_entry]
    warp_instance._num_frames_total = cam_entry.num_frames
    try:
        warp_instance.warp_it_num_cpus = tde4.getAvailableCPUCores()
    except Exception:
        warp_instance.warp_it_num_cpus = 1

    # Requester id expected by callback_run (GUI sets this when user clicks Run)
    if not hasattr(warp_instance, "req") or warp_instance.req is None:
        warp_instance.req = 0

    # State for timer callback and polling
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
        frames = glob.glob(os.path.join(_image_warp_poll_state.output_path, "*.exr"))
        current = len(frames)
        if current >= _image_warp_poll_state.expected_frames:
            if log:
                log.info("Image Warp complete: %d frames", current)
            _image_warp_poll_state.is_complete = True
            _image_warp_poll_state.is_running = False
            tde4.setTimerCallbackFunction("", 0)
            return
        elapsed = time.time() - _image_warp_poll_state.start_time
        if elapsed > IMAGE_WARP_POLL_TIMEOUT:
            if log:
                log.error("Image Warp timeout after %.0fs", elapsed)
            _image_warp_poll_state.is_running = False
            tde4.setTimerCallbackFunction("", 0)

    # 3DE looks up callback by name in __main__
    import __main__
    __main__._ayon_image_warp_poll = _ayon_image_warp_poll
    tde4.setTimerCallbackFunction("_ayon_image_warp_poll", 1000)

    if log:
        log.info("Starting Image Warp (callback_run)...")
    try:
        warp_instance.callback_run(warp_instance.req, "w007", 0)
    except Exception as e:
        tde4.setTimerCallbackFunction("", 0)
        _image_warp_poll_state = None
        raise KnownPublishError("Image Warp failed to start: %s" % e) from e

    if log:
        log.info("Waiting for Image Warp completion (polling every %ss)...", IMAGE_WARP_POLL_INTERVAL)
    start_poll = time.time()
    while _image_warp_poll_state.is_running:
        time.sleep(IMAGE_WARP_POLL_INTERVAL)
        frames = glob.glob(os.path.join(output_dir, "*.exr"))
        if len(frames) >= num_frames:
            if log:
                log.info("Detected %d frames - warp complete", len(frames))
            break
        if time.time() - start_poll > IMAGE_WARP_POLL_TIMEOUT:
            tde4.setTimerCallbackFunction("", 0)
            _image_warp_poll_state = None
            raise KnownPublishError(
                "Image Warp timeout - only %d/%d frames"
                % (len(frames), num_frames)
            )

    tde4.setTimerCallbackFunction("", 0)
    _image_warp_poll_state = None

    final_frames = sorted(glob.glob(os.path.join(output_dir, "*.exr")))
    if len(final_frames) < num_frames:
        raise KnownPublishError(
            "Incomplete warp: %d/%d frames" % (len(final_frames), num_frames)
        )
