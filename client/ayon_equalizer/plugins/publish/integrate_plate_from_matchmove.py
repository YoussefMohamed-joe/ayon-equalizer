"""Create a plate product pointing to the matchmove's undistorted_plate representation.

Runs after IntegrateAsset. Creates a plate product in AYON that references the
same undistorted_plate path (no duplicate files) so the loader shows a plate product.
"""
import os
import re
from typing import ClassVar

import pyblish.api
from ayon_api import (
    get_product_by_name,
    get_representations,
    get_version_by_name,
)
from ayon_api.operations import (
    OperationsSession,
    new_product_entity,
    new_representation_entity,
    new_version_entity,
)


class IntegratePlateFromMatchmove(pyblish.api.InstancePlugin):
    """Create plate product pointing to matchmove's undistorted_plate representation."""

    order = pyblish.api.IntegratorOrder + 0.25
    hosts: ClassVar[list] = ["equalizer"]
    label = "Integrate Plate from Matchmove (point to undistorted_plate)"
    families: ClassVar[list] = ["matchmove"]

    def process(self, instance: pyblish.api.Instance) -> None:
        if not self._has_undistorted_plate(instance):
            return
        version_entity = instance.data.get("versionEntity")
        if not version_entity:
            return
        folder_entity = instance.data.get("folderEntity")
        if not folder_entity:
            self.log.warning(
                "No folderEntity on instance %s, skipping plate.",
                instance.data.get("productName"),
            )
            return

        project_name = instance.context.data["projectName"]
        product_name = (
            instance.data.get("productName")
            or instance.data.get("name")
            or "matchmoveMain"
        )
        plate_product_name = f"{product_name}_plate"

        repres = get_representations(
            project_name,
            version_ids=[version_entity["id"]],
        )
        undistorted_rep = next(
            (r for r in repres if (r.get("name") or "").lower() == "undistorted_plate"),
            None,
        )
        if not undistorted_rep:
            self.log.debug(
                "No undistorted_plate rep for version %s, skipping.",
                version_entity.get("id"),
            )
            return

        op_session = OperationsSession()

        # Product
        existing_product = get_product_by_name(
            project_name, plate_product_name, folder_entity["id"],
        )
        plate_product = new_product_entity(
            name=plate_product_name,
            product_type="plate",
            folder_id=folder_entity["id"],
            entity_id=existing_product["id"] if existing_product else None,
        )
        if not existing_product:
            op_session.create_entity(project_name, "product", plate_product)
            self.log.info("Created plate product: %s", plate_product_name)
        else:
            plate_product["id"] = existing_product["id"]

        # Version
        version_number = version_entity["version"]
        existing_version = get_version_by_name(
            project_name, version_number, plate_product["id"],
        )

        frame_start, frame_end = self._resolve_frame_range(
            undistorted_rep, instance,
        )

        matchmove_attribs = dict(version_entity.get("attrib") or {})
        matchmove_attribs["frameStart"] = frame_start
        matchmove_attribs["frameEnd"] = frame_end
        matchmove_attribs.setdefault("handleStart", 0)
        matchmove_attribs.setdefault("handleEnd", 0)

        op_session.update_entity(
            project_name, "version", version_entity["id"],
            {"attrib": matchmove_attribs},
        )

        version_data = dict(version_entity.get("data") or {})
        version_data["families"] = ["plate"]

        plate_version = new_version_entity(
            version_number,
            plate_product["id"],
            data=version_data,
            attribs=dict(matchmove_attribs),
            entity_id=existing_version["id"] if existing_version else None,
        )
        if not existing_version:
            op_session.create_entity(project_name, "version", plate_version)
            self.log.debug("Created plate version v%03d", version_number)
        else:
            plate_version["id"] = existing_version["id"]
            op_session.update_entity(
                project_name, "version", plate_version["id"],
                {"data": version_data, "attrib": dict(matchmove_attribs)},
            )

        # Representation
        rep_attrib = undistorted_rep.get("attrib") or {}
        rep_data = undistorted_rep.get("data") or {}
        rep_files = list(undistorted_rep.get("files") or [])
        plate_rep_name = self._resolve_rep_name(rep_data, rep_files)

        existing_reps = get_representations(
            project_name, version_ids=[plate_version["id"]],
        )
        existing_rep = next(
            (r for r in existing_reps if (r.get("name") or "").lower() == plate_rep_name),
            None,
        )
        plate_rep = new_representation_entity(
            plate_rep_name,
            plate_version["id"],
            rep_files,
            data=rep_data,
            attribs={
                "path": rep_attrib.get("path", ""),
                "template": rep_attrib.get("template", ""),
            },
            entity_id=existing_rep["id"] if existing_rep else None,
        )
        if not existing_rep:
            op_session.create_entity(project_name, "representation", plate_rep)
        else:
            op_session.update_entity(
                project_name, "representation", plate_rep["id"],
                {
                    "files": rep_files,
                    "attrib": {
                        "path": rep_attrib.get("path", ""),
                        "template": rep_attrib.get("template", ""),
                    },
                },
            )
        self.log.info(
            "Plate product %s v%03d rep %s -> %s",
            plate_product_name, version_number,
            plate_rep_name, rep_attrib.get("path", "")[:80],
        )
        op_session.commit()

    @staticmethod
    def _has_undistorted_plate(instance: pyblish.api.Instance) -> bool:
        """True if instance has an undistorted_plate representation."""
        return any(
            (rep.get("name") or "").lower() == "undistorted_plate"
            for rep in instance.data.get("representations") or []
        )

    @staticmethod
    def _resolve_frame_range(
        undistorted_rep: dict,
        instance: "pyblish.api.Instance",
    ) -> tuple[int, int]:
        """Derive frame range from rep files, camera, or AYON default (1001)."""
        rep_files = undistorted_rep.get("files") or []
        frame_pattern = re.compile(r"\.(\d+)\.[^.]+$")
        frame_numbers = []
        for item in rep_files:
            name = item if isinstance(item, str) else (item.get("name") or item.get("path") or "")
            m = frame_pattern.search(name)
            if m:
                frame_numbers.append(int(m.group(1)))

        if frame_numbers:
            return min(frame_numbers), max(frame_numbers)

        cameras = instance.data.get("cameras") or []
        enabled_cams = [c for c in cameras if c.get("enabled")]
        if enabled_cams:
            try:
                p_start, p_end = enabled_cams[0]["playback_range"]
                return int(p_start), int(p_end)
            except Exception:
                pass

        frame_start = 1001
        frame_end = frame_start + max(0, len(rep_files) - 1) if rep_files else frame_start + 99
        return frame_start, frame_end

    @staticmethod
    def _resolve_rep_name(rep_data: dict, rep_files: list) -> str:
        """Get representation name from data ext or first file extension."""
        name = rep_data.get("ext") or ""
        if not name and rep_files:
            first = rep_files[0] if isinstance(rep_files[0], str) else (rep_files[0].get("name") or "")
            name = os.path.splitext(first)[1].lstrip(".")
        return (name or "jpg").lower()
