"""Extract project for Maya."""

import os
import re
from pathlib import Path
from typing import ClassVar

import pyblish.api
import tde4
from ayon_core.lib import import_filepath
from ayon_core.pipeline import (
    KnownPublishError,
    OptionalPyblishPluginMixin,
    publish,
)

from ayon_equalizer.api import ExtractScriptBase, maintained_model_selection
from ayon_equalizer.api.lib import maya_valid_name
from ayon_equalizer.api.publish_path import get_matchmove_publish_dir

EQUALIZER_7 = 7
EQUALIZER_8 = 8

class ExtractMatchmoveScriptMaya(publish.Extractor,
                                 ExtractScriptBase,
                                 OptionalPyblishPluginMixin):
    """Extract Maya MEL script for matchmove.

    This is using built-in export script from 3DEqualizer.
    """

    label = "Extract Maya Script"
    families: ClassVar[list] = ["matchmove"]
    hosts: ClassVar[list] = ["equalizer"]
    optional = True

    # Run after Extract Undistorted Plate (Image Warp) so the plate exists when we point the script at it
    order = pyblish.api.ExtractorOrder + 0.1

    # intentionally ignoring complexity warning (PLR0915 and PLR0912) because
    # of the nature of the export scripts in 3DEqualizer.
    def process(self, instance: pyblish.api.Instance) -> None:  # noqa: C901,PLR0915,PLR0912
        """Extract Maya script from 3DEqualizer.

        This method is using export script shipped with 3DEqualizer to
        maintain as much compatibility as possible. Instead of invoking it
        from the UI, it calls directly the function that is doing the export.
        For that it needs to pass some data that are collected in 3dequalizer
        from the UI, so we need to determine them from the instance itself and
        from the state of the project.

        """
        # Only run on matchmove instances from the host (plate instance has no creator_attributes)
        if "creator_attributes" not in instance.data:
            return
        if not self.is_active(instance.data):
            return
        attr_data = self.get_attr_values_from_data(instance.data)
        use_distortion = attr_data.get("distortion", False)

        # 3DE export expects main/overscan ratio (≤1.0 when overscan exists).
        # Our pct = overscan_resolution / main_resolution * 100, so:
        #   distortion OFF → pct = 100 → ratio = 1.0 (no scaling)
        #   distortion ON  → pct > 100 → ratio < 1.0 (camera frustum scaled)
        # This matches what 3DE's GUI passes when the user enables distortion.
        overscan_width = 100.0 / attr_data["overscan_percent_width"]
        overscan_height = 100.0 / attr_data["overscan_percent_height"]

        # import maya export script from 3DEqualizer
        exporter_path = instance.context.data["tde4_path"] / "sys_data" / "py_scripts" / "export_maya.py"  # noqa: E501
        self.log.debug("Importing %s", exporter_path.as_posix())
        exporter = import_filepath(exporter_path.as_posix())

        # get camera point group
        point_group = None
        point_groups = tde4.getPGroupList()
        for pg in point_groups:
            if tde4.getPGroupType(pg) == "CAMERA":
                point_group = pg
                break
        else:
            # this should never happen as it should be handled by validator
            error_msg = "No camera point group found."
            raise KnownPublishError(error_msg)

        # Here we subtract 1 because 3DE is computing the offset with an offset
        offset = tde4.getCameraFrameOffset(tde4.getCurrentCamera()) - 1

        staging_dir = self.staging_dir(instance)

        # Undistorted plate (if Distortion on) was extracted by the previous step:
        # "Extract Undistorted Plate (Image Warp)". We run after it.

        unit_scales = {
            "mm": 10.0,  # cm -> mm
            "cm": 1.0,  # cm -> cm
            "m": 0.01,  # cm -> m
            "in": 0.393701,  # cm -> in
            "ft": 0.0328084,  # cm -> ft
            "yd": 0.0109361  # cm -> yd
        }
        scale_factor = unit_scales[attr_data["units"]]
        model_selection_enum = instance.data["creator_attributes"]["model_selection"]  # noqa: E501

        with maintained_model_selection():
            # handle model selection
            # We are passing it to existing function that is expecting
            # this value to be an index of selection type.
            # 1 - No models
            # 2 - Selected models
            # 3 - All models
            if model_selection_enum == "__all__":
                model_selection = 3
            elif model_selection_enum == "__none__":
                model_selection = 1
            else:
                # take model from instance and set its selection flag on
                # turn off all others
                model_selection = 2
                point_groups = tde4.getPGroupList()
                for point_group in point_groups:
                    model_list = tde4.get3DModelList(point_group, 0)
                    if model_selection_enum in model_list:
                        model_selection = 2
                        tde4.set3DModelSelectionFlag(
                            point_group, instance.data["model_selection"], 1)
                        break

                    # clear all other model selections
                    for model in model_list:
                        tde4.set3DModelSelectionFlag(point_group, model, 0)

            file_path = Path(staging_dir) / "maya_export"
            if instance.context.data.get("tde4_version"):
                self.log.debug("Exporting to: %s", file_path.as_posix())

            # create representation data
            if "representations" not in instance.data:
                instance.data["representations"] = []

            if instance.context.data["tde4_version"].major == EQUALIZER_7:
                status = exporter._maya_export_mel_file(  # noqa: SLF001
                    f"{file_path.as_posix()}.mel",
                    point_group,
                    [
                        c["id"] for c in instance.data["cameras"]
                        if c["enabled"]
                    ],
                    model_selection,
                    overscan_width,
                    overscan_height,
                    1 if attr_data["export_uv_textures"] else 0,
                    scale_factor,
                    offset,
                    1 if attr_data["hide_reference_frame"] else 0,
                )

                representation = {
                    "name": "mel",
                    "ext": "mel",
                    "files": f"{file_path.name}.mel",
                    "stagingDir": staging_dir,
                }
            elif instance.context.data["tde4_version"].major == EQUALIZER_8:
                exporter.script_version = "4.7"
                status, npoly_warning = exporter._maya_export_python_file(  # noqa: SLF001
                    file_path.as_posix(),  # staging path,
                    point_group,  # camera point group,
                    [
                        c["id"] for c in instance.data["cameras"]
                        if c["enabled"]
                    ],
                    model_selection,
                    overscan_width,
                    overscan_height,
                    1 if attr_data["export_uv_textures"] else 0,
                    scale_factor,
                    offset,
                    1 if attr_data["hide_reference_frame"] else 0,
                    # scene_name
                    maya_valid_name(f"{instance.data['name']}_GRP"),
                    1 if attr_data["point_sets"] else 0,
                    1 if attr_data["export_2p5d"] else 0)
                if npoly_warning:
                    self.log.warning("npoly warning: %s", npoly_warning)
                representation = {
                    "name": "py",
                    "ext": "py",
                    "files": f"{file_path.name}.py",
                    "stagingDir": staging_dir,
                }

        if status != 1:
            # for EM102
            err_msg = f"Export failed {status}"
            raise KnownPublishError(err_msg)

        # When distortion is enabled, point Maya script to the undistorted
        # plate. Rewrite image paths in the exported Python script.
        if use_distortion and instance.context.data["tde4_version"].major == EQUALIZER_8:
            enabled_cams = [
                c for c in instance.data["cameras"]
                if c["enabled"]
            ]
            if enabled_cams:
                first_cam = enabled_cams[0]["id"]
                original_plate_pattern = enabled_cams[0]["path"]
                sattr = tde4.getCameraSequenceAttr(first_cam)
                start_frame = sattr[0]
                # Use AYON product name and ext (e.g. .jpg) set by Extract Undistorted Plate
                plate_base_name = instance.data.get("plate_base_name")
                plate_ext = instance.data.get("plate_ext", "jpg")
                if plate_base_name:
                    plate_pattern = f"{plate_base_name}.####.{plate_ext}"
                    first_frame_name = f"{plate_base_name}.{start_frame:04d}.{plate_ext}"
                else:
                    plate_pattern = f"frame.####.{plate_ext}"
                    first_frame_name = f"frame.{start_frame:04d}.{plate_ext}"
                full_dir = get_matchmove_publish_dir(instance)
                if full_dir:
                    plate_path = os.path.join(full_dir, plate_pattern).replace("\\", "/")
                    first_frame_path = os.path.join(full_dir, first_frame_name).replace("\\", "/")
                else:
                    plate_path = str(Path("..") / plate_pattern).replace("\\", "/")
                    first_frame_path = str(Path("..") / first_frame_name).replace("\\", "/")
                script_path = Path(f"{file_path.as_posix()}.py")
                if script_path.exists():
                    content = script_path.read_text(encoding="utf-8")
                    content = self._rewrite_image_paths(
                        content,
                        original_plate_pattern,
                        plate_path,
                        first_frame_path,
                        exporter,
                        start_frame,
                    )
                    script_path.write_text(content, encoding="utf-8")
                    self.log.debug(
                        "Rewrote Maya script to use undistorted plate: %s",
                        plate_path,
                    )

        self.log.debug("output: %s", file_path.as_posix())
        instance.data["representations"].append(representation)

    @staticmethod
    def _rewrite_image_paths(
        content: str,
        original_plate_pattern: str,
        new_plate_path: str,
        new_first_frame_path: str,
        exporter,
        start_frame: int,
    ) -> str:
        """Rewrite image paths in exported Maya Python script.

        Uses multiple strategies to find and replace the original plate
        path with the undistorted plate path:
        1. Try exact string replacement with various escaping variants
        2. Try the _maya_prepareImagePath result
        3. Fall back to regex matching on the filename portion
        """
        # Build all variants of the original path to try replacing
        original_fwd = original_plate_pattern.replace("\\", "/")
        original_back = original_plate_pattern.replace("/", "\\")
        original_double_back = original_back.replace("\\", "\\\\")

        replaced = False
        # Try each variant of the original path
        for variant in (original_double_back, original_back, original_fwd, original_plate_pattern):
            if variant and variant in content:
                content = content.replace(variant, new_plate_path)
                replaced = True
                break

        # Also try replacing the _maya_prepareImagePath result (first-frame path)
        try:
            maya_prepare = exporter._maya_prepareImagePath(  # noqa: SLF001
                original_plate_pattern, start_frame
            )
            if maya_prepare and maya_prepare in content:
                content = content.replace(maya_prepare, new_first_frame_path)
                replaced = True
        except Exception:
            pass

        # If exact match failed, try regex on the filename portion.
        # The 3DE exporter may have transformed the path, so we match on
        # just the base filename (with frame padding or frame number).
        if not replaced:
            original_basename = os.path.basename(original_fwd)
            if original_basename:
                # Escape for regex but allow flexible frame padding
                # e.g. "plate.1001.jpg" or "plate.####.jpg"
                base_no_ext = os.path.splitext(original_basename)[0]
                ext = os.path.splitext(original_basename)[1]
                # Match any path containing this filename with any number format
                escaped_base = re.escape(base_no_ext)
                escaped_ext = re.escape(ext)
                # Replace digits or # padding
                pattern = escaped_base.replace(r"\#\#\#\#", r"[#\d]+")
                pattern = re.sub(r"\\d\+|\d+", r"[#\\d]+", pattern)
                # Match the full quoted path containing this filename
                path_regex = re.compile(
                    r'(["\'])([^"\']*/?' + pattern + escaped_ext + r')\1'
                )
                content = path_regex.sub(
                    lambda m: m.group(1) + new_plate_path + m.group(1),
                    content,
                    count=0,
                )

        return content
