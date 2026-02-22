# Contributing and Merging with Upstream

This document explains how this fork is structured so you can **merge with the official AYON equalizer addon** with as few conflicts as possible, and how to keep code style consistent.

---

## 1. File layout: what is “ours” vs “theirs”

### Files that only exist in this fork (no upstream counterpart)

These are **additions**. When merging, upstream will not have them, so there are **no merge conflicts**; you just keep these files.

| Path | Purpose |
|------|--------|
| `client/ayon_equalizer/api/distorted_plate.py` | Image Warp + undistorted plate representation (callback_run, timer/poll, add representation). |
| `client/ayon_equalizer/api/publish_path.py` | Resolve full matchmove version folder path for script plate path. |
| `client/ayon_equalizer/api/plate_naming.py` | AYON-style plate base name and rename of staged frame.*.exr. |
| `client/ayon_equalizer/api/context_from_workfile.py` | Set context projectRoot/folderPath from current workfile path. |
| `client/ayon_equalizer/plugins/publish/extract_undistorted_plate.py` | Extractor that runs Image Warp when Distortion is on; adds undistorted_plate representation to the matchmove instance only. |
| `client/ayon_equalizer/plugins/publish/integrate_plate_from_matchmove.py` | After integrate: creates a plate product in AYON that points to the matchmove's undistorted_plate representation (same path, no duplicate files). |
| `docs/undistorted_plate_and_matchmove_publish.md` | Documentation for undistorted plate and matchmove publish. |
| `docs/CONTRIBUTING_AND_MERGE.md` | This file. |

### Files that likely exist upstream and we changed

Here you may get **merge conflicts** when pulling from upstream. Our changes are kept small and localized so conflicts are easier to resolve.

| Path | What we changed |
|------|------------------|
| `client/ayon_equalizer/plugins/publish/collect_workfile.py` | Set `currentFile`; call `set_project_root_from_path(context, current_file)` so full publish path can be resolved. |
| `client/ayon_equalizer/plugins/publish/extract_matchmove_script_maya.py` | Import `get_matchmove_publish_dir` from `api.publish_path`; when Distortion is on, rewrite plate path to full path (and AYON plate base name); guard so we only run on matchmove instances (`creator_attributes`). |

Strategy when merging:

- **collect_workfile.py:** Upstream may only set `context.data["currentFile"]`. Ours adds the import and one call to `set_project_root_from_path`. Re-apply that after resolving any conflict.
- **extract_matchmove_script_maya.py:** Upstream has no “plate path rewrite” or distortion handling. Our changes are: one import, early return when `creator_attributes` is missing, and the block that rewrites the script to the full plate path. Keep those blocks and fix any conflicts in the rest of the file.

---

## 2. Code style (match official addon)

So that our code looks like the rest of the addon and merges cleanly:

- **Imports:** Standard library first, then third party (`pyblish`, `tde4`, `ayon_core`), then local (`ayon_equalizer.api.*`). One import per line for long lists is fine.
- **Docstrings:** One-line module docstring at the top. Classes: one-line summary. Functions/methods: one-line or short description; use Returns/Raises only when it helps.
- **Types:** Use `ClassVar[list]` for plugin `families`/`hosts`. Use `from __future__ import annotations` and `Optional`, `Path`, etc. where the rest of the addon does. For pyblish instances we use `TYPE_CHECKING` and string quotes to avoid importing pyblish at runtime in helpers.
- **Naming:** `snake_case` for functions and variables; class names `CamelCase`. Match existing names in the same file (e.g. `staging_dir`, `instance.data`).
- **Comments:** Short inline comments for “why”, not “what”. Use `# noqa: E501` (or similar) only when a long line is intentional.
- **New API modules:** We do **not** export the new helpers from `api/__init__.py`. They are used only inside the addon (e.g. by extractors and collectors). That keeps the public API unchanged and avoids conflicts if upstream adds new exports.

---

## 3. Merge workflow (high level)

1. Fetch upstream and create a merge branch (or use your usual workflow).
2. **No conflict:** New files listed in section 1 (e.g. `distorted_plate.py`, `publish_path.py`, `extract_undistorted_plate.py`, docs). Keep them as-is.
3. **Possible conflict:** `collect_workfile.py`, `extract_matchmove_script_maya.py`. Resolve by keeping upstream structure and re-applying our small changes (projectRoot from workfile path; full plate path + distortion handling).
4. Run tests / a quick publish with Distortion on to confirm nothing broke.
5. If upstream adds similar features later, prefer their implementation and drop or adapt ours so the codebase stays in sync with official style and behaviour.

---

## 4. Summary

- **Our feature code** lives in **new files** (api helpers + extract_undistorted_plate + docs). Those won’t conflict with upstream.
- **Touches to “official” code** are **minimal** (one collector call, one import and one block in the Maya extractor), so merge conflicts are limited and easy to re-apply.
- **Style** matches the rest of the addon (imports, docstrings, types, naming) so merged code looks consistent and is easier to maintain.
