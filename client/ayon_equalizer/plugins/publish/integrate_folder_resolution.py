"""Update folder (shot) resolutionWidth/Height in AYON using overscan values from 3DEqualizer."""

from typing import ClassVar

import pyblish.api
import tde4
from ayon_api.operations import OperationsSession

from ayon_equalizer.api.overscan import OverscanError, bbdld_compute_bounding_box
from ayon_equalizer.plugins.publish.extract_undistorted_plate import _get_distortion


class IntegrateFolderResolution(pyblish.api.InstancePlugin):
    """Override the shot's resolution in AYON with the 3DEqualizer overscan dimensions."""

    order = pyblish.api.IntegratorOrder + 0.3
    label = "Integrate Folder Resolution (Overscan)"
    hosts: ClassVar[list] = ["equalizer"]
    families: ClassVar[list] = ["matchmove"]

    def process(self, instance: pyblish.api.Instance) -> None:
        """Update AYON folder resolutionWidth/Height from current camera overscan."""
        if not _get_distortion(instance.data):
            return

        folder_entity = instance.data.get("folderEntity")
        if not folder_entity:
            self.log.warning("No folderEntity on instance, skipping resolution update.")
            return

        project_name = instance.context.data["projectName"]
        cam = tde4.getCurrentCamera()

        try:
            _x, _y, box_width, box_height = bbdld_compute_bounding_box(cam)
        except OverscanError:
            self.log.warning("Could not compute overscan bounding box. Skipping folder update.", exc_info=True)
            return

        box_width = int(round(box_width))
        box_height = int(round(box_height))

        self.log.info(
            "Updating folder '%s' resolution to %dx%d",
            folder_entity.get("name"), box_width, box_height,
        )

        op = OperationsSession()
        op.update_entity(
            project_name,
            "folder",
            folder_entity["id"],
            {"attrib": {"resolutionWidth": box_width, "resolutionHeight": box_height}},
        )
        op.commit()
