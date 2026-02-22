"""Collect workfile and set projectRoot from path for publish path resolution."""
from typing import ClassVar

import pyblish.api
import tde4

from ayon_equalizer.api.context_from_workfile import set_project_root_from_path


class CollectWorkfile(pyblish.api.ContextPlugin):
    """Collect 3DE project as workfile; set projectRoot when path is under projects/."""

    order = pyblish.api.CollectorOrder
    hosts: ClassVar[list] = ["equalizer"]
    label = "Collect Workfile"

    def process(self, context: pyblish.api.Context) -> None:
        current_file = tde4.getProjectPath() or ""
        context.data["currentFile"] = current_file
        set_project_root_from_path(context, current_file)
