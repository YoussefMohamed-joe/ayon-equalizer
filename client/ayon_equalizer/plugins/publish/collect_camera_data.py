"""Collect camera data from the scene."""
from typing import ClassVar

import pyblish.api
import tde4


class CollectCameraData(pyblish.api.InstancePlugin):
    """Collect camera data from the scene."""

    order = pyblish.api.CollectorOrder
    families: ClassVar[list] = ["matchmove"]
    hosts: ClassVar[list] = ["equalizer"]
    label = "Collect camera data"

    def process(self, instance: pyblish.api.Instance) -> None:
        """Collect Camera data from 3DE.

        Handle camera selection. Possible values are:

           - ``__current__`` - current camera
           - ``__ref__`` - reference cameras
           - ``__seq__`` - sequence cameras
           - ``__all__`` - all cameras
           - ``camera_id`` - specific camera

        """
        try:
            camera_sel = instance.data["creator_attributes"]["camera_selection"]
        except KeyError:
            self.log.warning("No camera defined")
            return

        if camera_sel == "__all__":
            cameras = tde4.getCameraList()
        elif camera_sel == "__current__":
            cameras = [tde4.getCurrentCamera()]
        elif camera_sel in ["__ref__", "__seq__"]:
            cameras = [
                c for c in tde4.getCameraList()
                if tde4.getCameraType(c) == "REF_FRAME"
            ]
        else:
            if camera_sel not in tde4.getCameraList():
                self.log.warning("Invalid camera found")
                return
            cameras = [camera_sel]

        data = []
        for camera in cameras:
            data.append({
                "name": tde4.getCameraName(camera),
                "id": camera,
                "enabled": tde4.getCameraEnabledFlag(camera),
                "calculation_range": tde4.getCameraCalculationRange(camera),
                "playback_range": tde4.getCameraPlaybackRange(camera),
                "fov": tde4.getCameraFOV(camera),
                "fps": tde4.getCameraFPS(camera),
                "path": tde4.getCameraPath(camera),
            })

        instance.data["cameras"] = data
        self._collect_distortion_attributes(instance, data)

    def _collect_distortion_attributes(self, instance, cameras):
        """Save distortion state and overscan resolution to versionAttributes.

        When Distortion is ON in the creator: saves 'distorted' + the actual
        pixel resolution of the overscan image so downstream DCCs can override
        their render resolution on load.

        When Distortion is OFF: saves 'undistorted' only — no resolution saved,
        no override will happen downstream.
        """
        # The 'distortion' checkbox and overscan values are stored as publish attributes 
        # specifically under the ExtractMatchmoveScriptMaya plugin data.
        publish_attrs = instance.data.get("publish_attributes", {})
        extract_attrs = publish_attrs.get("ExtractMatchmoveScriptMaya", {})
        
        # Because we also injected them into creator_attributes or attribute_values, check both safely
        use_distortion = extract_attrs.get("distortion", False)

        if "versionAttributes" not in instance.data:
            instance.data["versionAttributes"] = {}

        if use_distortion:
            first_cam = next(
                (c["id"] for c in cameras if c["enabled"]),
                cameras[0]["id"] if cameras else None,
            )
            if first_cam:
                base_w = tde4.getCameraImageWidth(first_cam)
                base_h = tde4.getCameraImageHeight(first_cam)
            else:
                base_w, base_h = 1920, 1080

            overscan_pct_w = float(extract_attrs.get("overscan_percent_width", 100.0))
            overscan_pct_h = float(extract_attrs.get("overscan_percent_height", 100.0))

            overscan_w_px = int(round(base_w * overscan_pct_w / 100.0))
            overscan_h_px = int(round(base_h * overscan_pct_h / 100.0))

            instance.data["versionAttributes"]["mmDistortionState"] = True
            instance.data["versionAttributes"]["mmOverscanWidth"] = overscan_w_px
            instance.data["versionAttributes"]["mmOverscanHeight"] = overscan_h_px
            self.log.info("Distorted matchmove. Overscan resolution: %dx%d", overscan_w_px, overscan_h_px)
        else:
            instance.data["versionAttributes"]["mmDistortionState"] = False
            self.log.debug("Undistorted matchmove. No resolution override will be applied.")
