"""Create a plate product that points to the matchmove's undistorted_plate representation.

The undistorted_plate is published only on the matchmove instance (same path).
This plugin runs after Integrate and creates a plate product in AYON that
references the same representation (same path, no duplicate files) so the
loader shows a plate product. The plate representation uses the extension as
name (e.g. "jpg") so it loads like other addons' footage in Nuke.
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
    new_version_entity,
    new_representation_entity,
)


class IntegratePlateFromMatchmove(pyblish.api.InstancePlugin):
    """Create plate product pointing to matchmove's undistorted_plate representation.

    Runs after IntegrateAsset. For each integrated matchmove that has an
    undistorted_plate representation, creates a plate product (productName_plate)
    with a version and representation that point to the same path (no file copy).
    """

    order = pyblish.api.IntegratorOrder + 0.25
    hosts: ClassVar[list] = ["equalizer"]
    label = "Integrate Plate from Matchmove (point to undistorted_plate)"
    families: ClassVar[list] = ["matchmove"]

    def process(self, instance: pyblish.api.Instance) -> None:
        """Create plate product/version/representation pointing to matchmove rep."""
        if not self._has_undistorted_plate(instance):
            return
        version_entity = instance.data.get("versionEntity")
        if not version_entity:
            return
        folder_entity = instance.data.get("folderEntity")
        if not folder_entity:
            self.log.warning(
                "No folderEntity on instance %s, skipping plate product creation.",
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

        # Get the matchmove version's undistorted_plate representation from DB
        repres = get_representations(
            project_name,
            version_ids=[version_entity["id"]],
        )
        undistorted_rep = None
        for r in repres:
            if (r.get("name") or "").lower() == "undistorted_plate":
                undistorted_rep = r
                break
        if not undistorted_rep:
            self.log.debug(
                "No undistorted_plate representation found for version %s, skipping.",
                version_entity.get("id"),
            )
            return

        op_session = OperationsSession()

        # Plate product (same folder as matchmove)
        existing_plate_product = get_product_by_name(
            project_name,
            plate_product_name,
            folder_entity["id"],
        )
        plate_product = new_product_entity(
            name=plate_product_name,
            product_type="plate",
            folder_id=folder_entity["id"],
            entity_id=existing_plate_product["id"] if existing_plate_product else None,
        )
        if not existing_plate_product:
            op_session.create_entity(project_name, "product", plate_product)
            self.log.info("Created plate product: %s", plate_product_name)
        else:
            plate_product["id"] = existing_plate_product["id"]

        # Plate version (same version number as matchmove)
        version_number = version_entity["version"]
        existing_plate_version = get_version_by_name(
            project_name,
            version_number,
            plate_product["id"],
        )

        # Derive frame range for AYON:
        # 1) Prefer sequence frame numbers from the undistorted representation files
        #    (e.g. pip_sq01_matchmoveMain_v023.1001.jpg -> 1001–1059).
        # 2) Fallback: use camera playback range when available.
        # 3) Final fallback: 1001-based default (AYON/VFX standard).
        frame_start = frame_end = None
        rep_files = undistorted_rep.get("files") or []
        frame_numbers: list[int] = []
        frame_pattern = re.compile(r"\.(\d+)\.[^.]+$")
        for item in rep_files:
            if isinstance(item, str):
                name = item
            else:
                # AYON representation 'files' can also be dicts
                name = (
                    item.get("name")
                    or item.get("path")
                    or ""
                )
            m = frame_pattern.search(name)
            if m:
                try:
                    frame_numbers.append(int(m.group(1)))
                except ValueError:
                    continue
        if frame_numbers:
            frame_start = min(frame_numbers)
            frame_end = max(frame_numbers)

        cameras = instance.data.get("cameras") or []
        enabled_cams = [c for c in cameras if c.get("enabled")]
        if frame_start is None and enabled_cams:
            try:
                p_start, p_end = enabled_cams[0]["playback_range"]
                frame_start = int(p_start) if p_start is not None else None
                frame_end = int(p_end) if p_end is not None else None
            except Exception:  # pragma: no cover - defensive
                pass
        # AYON default: start at 1001, end 1001+len(files)-1 or 1100 if unknown
        if frame_start is None:
            frame_start = 1001
        if frame_end is None:
            rep_files_count = len(rep_files)
            frame_end = (
                frame_start + max(0, rep_files_count - 1)
                if rep_files_count
                else (frame_start + 99)
            )

        # Matchmove version attribs: ensure numeric frameStart/frameEnd/handles.
        matchmove_attribs = dict(version_entity.get("attrib") or {})
        handle_start = int(matchmove_attribs.get("handleStart") or 0)
        handle_end = int(matchmove_attribs.get("handleEnd") or 0)
        matchmove_attribs["frameStart"] = frame_start
        matchmove_attribs["frameEnd"] = frame_end
        matchmove_attribs["handleStart"] = handle_start
        matchmove_attribs["handleEnd"] = handle_end

        # Update the original matchmove version in DB so any loader (including
        # loading the matchmove itself) sees a proper frame range.
        op_session.update_entity(
            project_name,
            "version",
            version_entity["id"],
            {"attrib": matchmove_attribs},
        )

        # Plate version data/attribs: reuse matchmove data, set families to plate,
        # and copy the (now fixed) attribs so plate behaves like normal footage.
        version_data = dict(version_entity.get("data") or {})
        version_data["families"] = ["plate"]
        version_attribs = dict(matchmove_attribs)
        plate_version = new_version_entity(
            version_number,
            plate_product["id"],
            data=version_data,
            attribs=version_attribs,
            entity_id=existing_plate_version["id"] if existing_plate_version else None,
        )
        if not existing_plate_version:
            op_session.create_entity(project_name, "version", plate_version)
            self.log.debug("Created plate version v%03d", version_number)
        else:
            plate_version["id"] = existing_plate_version["id"]
            op_session.update_entity(
                project_name,
                "version",
                plate_version["id"],
                {
                    "data": version_data,
                    "attrib": version_attribs,
                },
            )

        # Plate representation: same path and files as matchmove's undistorted_plate.
        # Use extension as representation name (e.g. "jpg") so it loads like other addons' footage.
        rep_attrib = undistorted_rep.get("attrib") or {}
        rep_data = undistorted_rep.get("data") or {}
        rep_files = list(undistorted_rep.get("files") or [])
        plate_rep_name = (
            rep_data.get("ext")
            or (os.path.splitext(rep_files[0])[1].lstrip(".") if rep_files else "jpg")
        )
        if isinstance(plate_rep_name, str):
            plate_rep_name = plate_rep_name.lower()
        else:
            plate_rep_name = "jpg"
        existing_plate_reps = get_representations(
            project_name,
            version_ids=[plate_version["id"]],
        )
        existing_plate_rep = next(
            (r for r in existing_plate_reps if (r.get("name") or "").lower() == plate_rep_name),
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
            entity_id=existing_plate_rep["id"] if existing_plate_rep else None,
        )
        if not existing_plate_rep:
            op_session.create_entity(project_name, "representation", plate_rep)
        else:
            op_session.update_entity(
                project_name,
                "representation",
                plate_rep["id"],
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
            plate_product_name,
            version_number,
            plate_rep_name,
            rep_attrib.get("path", "")[:80],
        )

        op_session.commit()

    @staticmethod
    def _has_undistorted_plate(instance: pyblish.api.Instance) -> bool:
        """True if instance has an undistorted_plate representation."""
        for rep in instance.data.get("representations") or []:
            if (rep.get("name") or "").lower() == "undistorted_plate":
                return True
        return False
