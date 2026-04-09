"""Extract Nuke Lens Distortion data from 3DEqualizer."""

from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pyblish.api
import tde4
from ayon_core.lib import EnumDef, import_filepath
from ayon_core.pipeline import OptionalPyblishPluginMixin, publish

from ayon_equalizer.api.overscan import OverscanError, bbdld_compute_bounding_box


class ExtractLensDistortionNuke(publish.Extractor, OptionalPyblishPluginMixin):
    """Export a Nuke .nk file: BlackOutside -> LD node -> Reformat, with overscan dimensions."""

    label = "Extract Lens Distortion Nuke node"
    families: ClassVar[list] = ["lensDistortion"]
    hosts: ClassVar[list] = ["equalizer"]
    order = pyblish.api.ExtractorOrder

    _BLACK_OUTSIDE_SNIPPET = (
        "BlackOutside {\n"
        " name BlackOutside1\n"
        "}\n"
    )

    _REFORMAT_SNIPPET = (
        "Reformat {{\n"
        " type \"to box\"\n"
        " box_width {box_width}\n"
        " box_height {box_height}\n"
        " box_fixed false\n"
        " resize none\n"
        " center true\n"
        " filter cubic\n"
        " name Reformat1\n"
        "}}\n"
    )

    def process(self, instance: pyblish.api.Instance) -> None:
        """Export the 3DEqualizer LD node and wrap it with BlackOutside + Reformat."""
        if not self.is_active(instance.data):
            return

        cam = tde4.getCurrentCamera()
        offset = tde4.getCameraFrameOffset(cam) - 1
        staging_dir = self.staging_dir(instance)
        file_path = Path(staging_dir) / "nuke_ld_export.nk"
        attr_data = self.get_attr_values_from_data(instance.data)

        def patched_getWidgetValue(_, key: str) -> str:  # noqa: N802, ANN001
            """Return fovMode for the FOV widget key, empty string otherwise."""
            return attr_data["fovMode"] if key == "option_menu_fov_mode" else ""

        exporter_path = (
            instance.context.data["tde4_path"]
            / "sys_data"
            / "py_scripts"
            / "export_nuke_LD_3DE4_Lens_Distortion_Node.py"
        )
        self.log.debug("Importing %s", exporter_path.as_posix())
        exporter = import_filepath(exporter_path.as_posix())
        with patch("tde4.getWidgetValue", patched_getWidgetValue):
            exporter.exportNukeDewarpNode(cam, offset, file_path.as_posix())

        self._wrap_nk_file(cam, file_path)

        if "representations" not in instance.data:
            instance.data["representations"] = []

        instance.data["representations"].append({
            "name": "lensDistortion",
            "ext": "nk",
            "files": file_path.name,
            "stagingDir": staging_dir,
        })
        self.log.debug("output: %s", file_path.as_posix())

    def _wrap_nk_file(self, cam, file_path: Path) -> None:
        """Prepend BlackOutside1 and append Reformat1 (overscan dimensions) to the exported .nk file."""
        try:
            _x, _y, box_width, box_height = bbdld_compute_bounding_box(cam)
        except OverscanError:
            self.log.warning(
                "Could not compute overscan bounding box; Reformat node will use 200x200 as fallback.",
                exc_info=True,
            )
            box_width, box_height = 200, 200

        box_width = int(round(box_width))
        box_height = int(round(box_height))

        reformat = self._REFORMAT_SNIPPET.format(box_width=box_width, box_height=box_height)
        wrapped = self._BLACK_OUTSIDE_SNIPPET + file_path.read_text(encoding="utf-8") + reformat
        file_path.write_text(wrapped, encoding="utf-8")

    @classmethod
    def get_attribute_defs(cls) -> list:
        """Return instance attribute definitions for the lensDistortion creator."""
        return [
            *super().get_attribute_defs(),
            EnumDef(
                "fovMode",
                label="FOV Mode",
                items=[
                    {"value": "1", "label": "legacy"},
                    {"value": "2", "label": "new (v8+)"},
                ],
                tooltip="FOV mode (legacy or new)",
                default="legacy",
            ),
        ]
