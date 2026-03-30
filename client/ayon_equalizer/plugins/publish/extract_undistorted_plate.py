"""Extract undistorted plate via Image Warp when Distortion is on."""
from typing import ClassVar

import pyblish.api
from ayon_core.pipeline import publish

from ayon_equalizer.api.distorted_plate import run_image_warp_and_add_representation

_EXTRACT_MAYA_PLUGIN = "ExtractMatchmoveScriptMaya"
ORDER_PLATE_FIRST = pyblish.api.ExtractorOrder - 0.1


def _get_distortion(instance_data: dict) -> bool:
    """True if Distortion is enabled for this instance."""
    attrs = instance_data.get("attribute_values") or {}
    if attrs.get("distortion", False):
        return True
    pub = instance_data.get("publish_attributes") or {}
    plugin_attrs = pub.get(_EXTRACT_MAYA_PLUGIN) or {}
    return bool(plugin_attrs.get("distortion", False))


class ExtractUndistortedPlate(publish.Extractor):
    """Extract undistorted plate via Image Warp. Runs before Maya extractor."""

    label = "Extract Undistorted Plate (Image Warp)"
    families: ClassVar[list] = ["matchmove"]
    hosts: ClassVar[list] = ["equalizer"]
    optional = False
    order = ORDER_PLATE_FIRST

    def process(self, instance: pyblish.api.Instance) -> None:
        if not _get_distortion(instance.data):
            return
        staging_dir = self.staging_dir(instance)
        tde4_path = instance.context.data["tde4_path"]
        run_image_warp_and_add_representation(
            instance,
            staging_dir,
            tde4_path,
            self.log,
        )
