"""Create a plate product that points to the matchmove's undistorted_plate representation.

The undistorted_plate is published only on the matchmove instance (same path).
This plugin runs after Integrate and creates a plate product in AYON that
references the same representation (same path, no duplicate files) so the
loader shows a plate product.
"""

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
        # Reuse matchmove version data, set families to plate
        version_data = dict(version_entity.get("data") or {})
        version_data["families"] = ["plate"]
        plate_version = new_version_entity(
            version_number,
            plate_product["id"],
            data=version_data,
            entity_id=existing_plate_version["id"] if existing_plate_version else None,
        )
        if not existing_plate_version:
            op_session.create_entity(project_name, "version", plate_version)
            self.log.debug("Created plate version v%03d", version_number)
        else:
            plate_version["id"] = existing_plate_version["id"]

        # Plate representation: same path and files as matchmove's undistorted_plate
        rep_attrib = undistorted_rep.get("attrib") or {}
        rep_data = undistorted_rep.get("data") or {}
        rep_files = list(undistorted_rep.get("files") or [])
        existing_plate_reps = get_representations(
            project_name,
            version_ids=[plate_version["id"]],
        )
        existing_undistorted = next(
            (r for r in existing_plate_reps if (r.get("name") or "").lower() == "undistorted_plate"),
            None,
        )
        plate_rep = new_representation_entity(
            "undistorted_plate",
            plate_version["id"],
            rep_files,
            data=rep_data,
            attribs={
                "path": rep_attrib.get("path", ""),
                "template": rep_attrib.get("template", ""),
            },
            entity_id=existing_undistorted["id"] if existing_undistorted else None,
        )
        if not existing_undistorted:
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
            "Plate product %s v%03d points to matchmove undistorted_plate: %s",
            plate_product_name,
            version_number,
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
