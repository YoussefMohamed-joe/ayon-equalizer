"""Extract Nuke Lens Distortion data from 3DEqualizer."""
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pyblish.api
import tde4
from ayon_core.lib import EnumDef, import_filepath
from ayon_core.pipeline import OptionalPyblishPluginMixin, publish

from ayon_equalizer.api.overscan import bbdld_compute_bounding_box


class ExtractLensDistortionNuke(publish.Extractor,
                                OptionalPyblishPluginMixin):
    """Extract Nuke Lens Distortion data.

    Unfortunately built-in export script from 3DEqualizer is bound to its UI,
    and it is not possible to call it directly from Python. Because of that,
    we are executing the script in the same way as artist would do it, but
    we are patching the UI to silence it and to avoid any user interaction.

    The exported .nk file is post-processed to wrap the raw Lens Distortion
    node with:
        1. A ``BlackOutside1`` node (before the LD node)
        2. A ``Reformat1`` node (after the LD node) whose box_width /
           box_height are taken directly from the 3DEqualizer overscan
           bounding box for the current camera.  The Reformat settings
           match the reference image:
               type         "to box"
               resize        none
               filter        cubic
               center        true

    TODO: Utilize attributes defined in ExtractScriptBase
    """

    label = "Extract Lens Distortion Nuke node"
    families: ClassVar[list] = ["lensDistortion"]
    hosts: ClassVar[list] = ["equalizer"]

    order = pyblish.api.ExtractorOrder

    # ------------------------------------------------------------------
    # Nuke node snippets
    # ------------------------------------------------------------------

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
        """Extract Nuke Lens Distortion script from 3DEqualizer."""
        if not self.is_active(instance.data):
            return

        cam = tde4.getCurrentCamera()
        offset = tde4.getCameraFrameOffset(cam) - 1
        staging_dir = self.staging_dir(instance)
        file_path = Path(staging_dir) / "nuke_ld_export.nk"
        attr_data = self.get_attr_values_from_data(instance.data)

        # these patched methods are used to silence 3DEqualizer UI:
        def patched_getWidgetValue(_, key: str) -> str:    # noqa: N802, ANN001
            """Return value for given key in widget."""
            return attr_data["fovMode"] if key == "option_menu_fov_mode" else ""  # noqa: E501

        # import export script from 3DEqualizer
        exporter_path = instance.context.data["tde4_path"] / "sys_data" / "py_scripts" / "export_nuke_LD_3DE4_Lens_Distortion_Node.py"  # noqa: E501
        self.log.debug("Importing %s", exporter_path.as_posix())
        exporter = import_filepath(exporter_path.as_posix())
        with patch("tde4.getWidgetValue", patched_getWidgetValue):
                exporter.exportNukeDewarpNode(
                    cam, offset, file_path.as_posix())

        # ------------------------------------------------------------------
        # Post-process: wrap the exported LD node with BlackOutside + Reformat
        # ------------------------------------------------------------------
        self._wrap_with_black_outside_and_reformat(cam, file_path)

        # create representation data
        if "representations" not in instance.data:
            instance.data["representations"] = []

        representation = {
            "name": "lensDistortion",
            "ext": "nk",
            "files": file_path.name,
            "stagingDir": staging_dir,
        }
        self.log.debug("output: %s", file_path.as_posix())
        instance.data["representations"].append(representation)

    def _wrap_with_black_outside_and_reformat(
        self, cam, file_path: Path
    ) -> None:
        """Wrap the exported Nuke file with BlackOutside and Reformat nodes.

        The final node order in the .nk file will be:
            BlackOutside1  ->  <LD node(s) from 3DE>  ->  Reformat1

        Args:
            cam: 3DEqualizer camera handle used to retrieve overscan dimensions.
            file_path: Path to the already-generated Nuke script.
        """
        # Compute overscan bounding box -> (x_min, y_min, width, height)
        try:
            _x, _y, box_width, box_height = bbdld_compute_bounding_box(cam)
        except Exception:
            self.log.warning(
                "Could not compute overscan bounding box; "
                "Reformat node will use 200x200 as fallback.",
                exc_info=True,
            )
            box_width, box_height = 200, 200

        # Round to integers - Nuke Reformat expects integer pixel values
        box_width = int(round(box_width))
        box_height = int(round(box_height))
        self.log.debug(
            "Overscan bounding box for Reformat: %dx%d", box_width, box_height
        )

        ld_content = file_path.read_text(encoding="utf-8")

        reformat_snippet = self._REFORMAT_SNIPPET.format(
            box_width=box_width,
            box_height=box_height,
        )

        wrapped = (
            self._BLACK_OUTSIDE_SNIPPET
            + ld_content
            + reformat_snippet
        )
        file_path.write_text(wrapped, encoding="utf-8")
        self.log.debug(
            "Wrapped Nuke LD script with BlackOutside + Reformat: %s",
            file_path.as_posix(),
        )

    @classmethod
    def get_attribute_defs(cls) -> list:
        """Return instance attribute definitions."""
        return [
            *super().get_attribute_defs(),
            EnumDef("fovMode",
                    label="FOV Mode",
                    items=[
                        {"value": "1", "label": "legacy"},
                        {"value": "2", "label": "new (v8+)"}],
                    tooltip="FOV mode (legacy or new)",
                    default="legacy"),
        ]
