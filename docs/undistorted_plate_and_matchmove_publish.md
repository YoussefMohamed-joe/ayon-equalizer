# Undistorted Plate and Matchmove Publish

This document explains how the AYON 3DEqualizer addon handles **undistorted plate** extraction when **Distortion** is enabled on a matchmove, and why the implementation is structured this way.

---

## 1. What This Feature Does

When you create a **matchmove** with **Distortion** enabled and then publish:

1. **Image Warp** runs automatically (no manual “Run” in 3DE’s Image Warp GUI).
2. The undistorted EXR sequence is written to a staging folder, then **renamed** to AYON-style filenames (e.g. `pip_sq01_matchmoveMain_v014.1001.exr`).
3. The **undistorted_plate** representation stays on the **matchmove** instance (same path). A post-integrate plugin creates a **plate product** in AYON (e.g. `matchmoveMain_plate`) that **points to** that representation (same path, no duplicate files), so the loader shows a plate product.
4. The **Maya export script** is rewritten so the plate path in the script is the **full publish path** (e.g. `X:/projects/pipetest/shots/sq01/publish/matchmove/matchmoveMain/v014/pip_sq01_matchmoveMain_v014.####.exr`), not a relative `..\` path.
5. AYON publishes the matchmove script and the plate EXRs into the **same version folder** (e.g. `.../matchmoveMain/v014/`), so the script and the plate EXRs live together.

Result: one publish produces the matchmove script and a **plate product** (undistorted EXRs) in the right place, with the script pointing at the plate by full path and correct AYON naming.

---

## 2. Why We Do It This Way

### 2.1 Run Image Warp via `callback_run`, Not the Binary

- **What we tried first:** Driving the Image Warp **binary** (`sdv_image_comp_pipe_io`) from Python (stdin: `get_version`, `set_num_threads`, `data`, minil graph, `run`). The binary **exits with return code -1** when run from the addon's publish context, and no frames are written. The same camera/plate works when the user clicks Run in the Image Warp GUI.
- **What we use instead:** Load 3DE's **sdv_image_warp_gui** script and call **`callback_run(req, "w007", 0)`**, the same entry point the GUI uses. We build the same structures (e.g. `tde4_objects` camera, `camera_entry`, output dir, overscan) and start the warp via this callback. A **timer callback** plus **polling** (e.g. every 2 seconds) wait until the expected number of `*.exr` files appear or a timeout (e.g. 10 minutes).

So: we use the **same code path as the GUI** so the warp actually runs and writes frames, and we avoid relying on the binary in a context where it fails.

### 2.2 Full Publish Path in the Maya Script (Not `..\`)

- **Why full path:** The script may be opened from different working directories. A relative path like `..\frame.1001.exr` only works if the current working directory is the script's folder. Using the **full path** to the published plate (e.g. `X:/projects/.../v014/pip_sq01_matchmoveMain_v014.1001.exr`) makes the script work regardless of CWD.
- **How we get the path:** We resolve the matchmove **version folder** path (e.g. `.../matchmoveMain/v014`) using, in order: AYON `get_project_roots` (if available), parsing `currentFile` when it's under `.../projects/Name/...`, `context.data["projectRoot"]` (set by the workfile collector), instance/context data, or env vars like `AYON_PROJECT_ROOT`. The plate path is then: **that folder** + **AYON-style plate filename**. All of this lives in a small helper module so the main extractor stays minimal.

### 2.3 AYON-Style Filenames (e.g. `pip_sq01_matchmoveMain_v014.1001.exr`)

- **Why rename:** So the published files follow the same naming convention as the rest of AYON (project code, folder, product name, version). That keeps the undistorted plate clearly tied to the matchmove product and makes it easy for tools and artists to recognise.
- **When we rename:** After Image Warp has finished writing `frame.1001.exr`, `frame.1002.exr`, etc. We wait a short time (e.g. 1.5 s) so the warp process releases file handles (avoids Windows "file in use" errors), then rename in place to `{project_code}_{folder}_{product}_v{version}.NNNN.exr` and list those new names in the representation's `files`. The Maya script path uses the same base name so it points at the renamed files.

### 2.4 Plate Product, Same Path as Matchmove

- The undistorted EXRs are published only on the **matchmove** (one representation, same path). A post-integrate plugin creates a **plate product** in AYON (e.g. `matchmoveMain_plate`) that **points to** that representation (same path, no duplicate files), so the loader shows a plate product. One version folder contains the Maya script and the plate EXRs.

## 2. Why We Do It This Way

### 2.1 Run Image Warp via `callback_run`, Not the Binary

- **What we tried first:** Driving the Image Warp **binary** (`sdv_image_comp_pipe_io`) from Python (stdin: `get_version`, `set_num_threads`, `data`, minil graph, `run`). The binary **exits with return code -1** when run from the addon’s publish context, and no frames are written. The same camera/plate works when the user clicks Run in the Image Warp GUI.
- **What we use instead:** Load 3DE’s **sdv_image_warp_gui** script and call **`callback_run(req, "w007", 0)`**, the same entry point the GUI uses. We build the same structures (e.g. `tde4_objects` camera, `camera_entry`, output dir, overscan) and start the warp via this callback. A **timer callback** plus **polling** (e.g. every 2 seconds) wait until the expected number of `*.exr` files appear or a timeout (e.g. 10 minutes).

So: we use the **same code path as the GUI** so the warp actually runs and writes frames, and we avoid relying on the binary in a context where it fails.

### 2.2 Full Publish Path in the Maya Script (Not `..\`)

- **Why full path:** The script may be opened from different working directories. A relative path like `..\frame.1001.exr` only works if the current working directory is the script’s folder. Using the **full path** to the published plate (e.g. `X:/projects/.../v014/pip_sq01_matchmoveMain_v014.1001.exr`) makes the script work regardless of CWD.
- **How we get the path:** We resolve the matchmove **version folder** path (e.g. `.../matchmoveMain/v014`) using, in order: AYON `get_project_roots` (if available), parsing `currentFile` when it’s under `.../projects/Name/...`, `context.data["projectRoot"]` (set by the workfile collector), instance/context data, or env vars like `AYON_PROJECT_ROOT`. The plate path is then: **that folder** + **AYON-style plate filename**. All of this lives in a small helper module so the main extractor stays minimal.

### 2.3 AYON-Style Filenames (e.g. `pip_sq01_matchmoveMain_v014.1001.exr`)

- **Why rename:** So the published files follow the same naming convention as the rest of AYON (project code, folder, product name, version). That keeps the undistorted plate clearly tied to the matchmove product and makes it easy for tools and artists to recognise.
- **When we rename:** After Image Warp has finished writing `frame.1001.exr`, `frame.1002.exr`, etc. We wait a short time (e.g. 1.5 s) so the warp process releases file handles (avoids Windows “file in use” errors), then rename in place to `{project_code}_{folder}_{product}_v{version}.NNNN.exr` and list those new names in the representation’s `files`. The Maya script path uses the same base name so it points at the renamed files.

### 2.4 One Product, Same Version Folder (No Separate “Plate” Product)

- The undistorted EXRs are **not** a separate AYON product. They are a **representation** (`undistorted_plate`) on the **matchmove** product. AYON publishes them into the **same version folder** as the matchmove (e.g. `.../matchmoveMain/v014/`). So you get one version folder containing both the Maya script and the plate EXRs, and the script path we write matches that layout. A collector creates the plate instance for each matchmove with Distortion on; the extractor adds the EXR representation to that instance.

---

## 3. Publish Flow (Order of Operations)

1. **Collect**
   - Workfile collector sets `context.data["currentFile"]` and, when the path is under `.../projects/...`, sets `projectRoot` and `folderPath` so the full publish path can be resolved later.
2. **Extract (order: plate first, then Maya)**
   - **Extract Undistorted Plate** (runs first):
     - Runs Image Warp via `callback_run`, waits for completion (timer + polling).
     - Renames staged `frame.*.exr` to AYON-style names.
     - Adds the `undistorted_plate` representation to the **matchmove** instance only; sets `instance.data["plate_base_name"]` for the Maya extractor.
   - **Extract Maya Script** (runs after):
     - Exports the Maya script as usual.
     - If Distortion was on: rewrites the plate path in the script to the **full path** using the resolved version folder and `plate_base_name` (e.g. `.../v014/pip_sq01_matchmoveMain_v014.####.exr`).
3. **Integrate**
   - AYON integrates the matchmove product (script + undistorted_plate EXRs) into the version folder.
   - **Integrate Plate from Matchmove** creates a plate product in AYON (e.g. `matchmoveMain_plate`) that points to the same undistorted_plate representation (same path, no duplicate files), so the loader shows a plate product.

---

## 4. Where the Logic Lives (and Why)

To keep **main/official plugin code** small and clear, the extra logic is in **dedicated modules**:

| Module | Role |
|--------|------|
| **`api/distorted_plate.py`** | Single place for “run Image Warp and add representation”: calls 3DE’s warp via `callback_run`, then uses helpers for naming and representation. |
| **`api/publish_path.py`** | Resolves the **full path** to the matchmove version folder (`get_matchmove_publish_dir(instance)`). Used by the Maya extractor to build the plate path. |
| **`api/plate_naming.py`** | AYON-style **plate base name** from instance/context (`get_plate_base_name`) and **rename** of staged `frame.*.exr` to that name (`rename_frames_to_ayon_style`). |
| **`api/context_from_workfile.py`** | Sets **projectRoot** and **folderPath** on the publish context from the current workfile path (`set_project_root_from_path`), so the full publish path can be built even when AYON’s `get_project_roots` is not available. |

The **extractors** and **collectors** then only do thin calls into these modules, so changes to path resolution or naming don’t clutter the main publish plugins.

---

## 5. Overscan and Distortion

- **Overscan** comes from the camera’s lens distortion (same math as the “Overscan %” in the matchmove form). It is injected when creating the matchmove and when publishing, so the same values are used for Image Warp and for the Maya export (overscan width/height).
- **Distortion** is a single toggle: when it’s on, we run Image Warp, add the undistorted plate representation, and rewrite the Maya script to point at that plate. There is no separate “Extract Distorted Plate” step; the one “Distortion” option controls both behaviour and the undistorted plate.

---

## 6. Summary

- **Image Warp** is run via the same GUI entry point (`callback_run`) and a timer/poll wait, so it works from the addon.
- The **plate path in the Maya script** is the **full publish path** and uses **AYON-style filenames**, so the script finds the plate regardless of CWD and matches AYON naming.
- The **undistorted plate** is published as a **plate product** in the **same version folder** as the matchmove.
- **Path resolution**, **plate naming**, and **workfile context** are in **small, separate modules** so the main publish code stays minimal and easy to maintain.

**See also:** [Contributing and merging with upstream](CONTRIBUTING_AND_MERGE.md) for which files are custom vs modified and how to merge with the official AYON equalizer addon with minimal conflicts.
