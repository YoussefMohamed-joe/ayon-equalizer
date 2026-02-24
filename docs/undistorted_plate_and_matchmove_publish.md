## Undistorted plate and matchmove publish

This document explains how the 3DEqualizer AYON addon:

- Runs **Image Warp** automatically when Distortion is on.
- Publishes the **undistorted plate** together with the **matchmove**.
- Creates a separate **plate product** (`matchmoveMain_plate`) that **points to** the same files.
- Sets a **proper 1001‑based frame range** so Nuke’s **Load Clip** treats it like any other plate.

---

### 1. Image Warp and staging

- When you publish a `matchmove` with **Distortion** enabled:
  - The addon calls 3DE’s **Image Warp GUI script** via `callback_run`, same as pressing “Run” by hand.
  - The undistorted frames are written to a **temporary staging folder**:
    - e.g. `.../Temp/ay_tmp_xxx/undistorted_plate/frame.1001.jpg` … `frame.1059.jpg`.
  - We **poll** until we see the expected number of frames, with a timeout.

---

### 2. AYON‑style renaming (multi‑pass, Windows‑safe)

- After the warp finishes we rename to an **AYON‑style base name**:
  - `pip_sq01_matchmoveMain_v024.1001.jpg` … `pip_sq01_matchmoveMain_v024.1059.jpg`
  - The base name is built from project code, folder, product, and version.
- Renaming is done by `rename_frames_to_ayon_style`:
  - It does **multiple passes** over `frame.*.jpg` with short sleeps in‑between.
  - On Windows, Image Warp can still hold a file handle for a moment; when that happens you will see warnings like  
    “Could not rename frame.1001.jpg … file is being used by another process…”.
  - Later passes retry and usually succeed once 3DE releases the file.
  - The final `files` list for the representation is built from  
    `pip_sq01_matchmoveMain_v024.*.jpg` only, so AYON sees a **clean sequence**.

Result: even if you see a **rename warning on the first pass**, the published plate is still correct.

---

### 3. Matchmove representation on the instance

- The matchmove instance receives a single representation:

  - `name`: `undistorted_plate` (internal name for our tools).
  - `ext`: `jpg` (or `exr` if you change `IMAGE_WARP_EXT`).
  - `stagingDir`: the staging `undistorted_plate` folder.
  - `files`: the renamed sequence (AYON‑style base name + frame numbers).
  - `data.ext`: the extension (so downstream can recover it).
  - `colorspaceData.colorspace`: currently `"ACES - ACEScg"` for loaders that read it.

- This representation lives only on the **matchmove** product; no duplicate files are created.

---

### 4. Plate product pointing to the same files

After core **Integrate**, the custom plugin
`IntegratePlateFromMatchmove` runs and:

- Looks up the matchmove’s `undistorted_plate` representation in the DB.
- Creates (or updates) a **plate product**:
  - Name: `<matchmove_product_name>_plate` (e.g. `matchmoveMain_plate`).
  - Type: `plate`.
- Creates (or updates) a **plate version** with:
  - Same **version number** as the matchmove.
  - `data.families = ["plate"]`.
  - **Attribs** (see next section) so loaders see a normal frame range.
- Creates (or updates) a **plate representation** that:
  - Uses the **extension as name** (e.g. `"jpg"`), same as Nuke’s own source publish.
  - Points to the **same `files` and `attrib.path/template`** as the matchmove’s `undistorted_plate`.

So in AYON you see both:

- `matchmoveMain` (matchmove product, with the undistorted representation).
- `matchmoveMain_plate` (plate product), without duplicating any files.

---

### 5. Frame range and handles (1001‑based, AYON‑friendly)

To make Nuke’s **Load Clip** treat the plate like normal footage, the
integrate plugin fixes the version metadata:

- It derives the **frame numbers from the filenames**:
  - e.g. `...v024.1001.jpg` … `...v024.1059.jpg` → `frameStart=1001`, `frameEnd=1059`.
  - If for some reason it can’t parse the filenames:
    - It falls back to the first enabled camera’s **playback range**, and
    - As a last resort, it defaults to a 1001‑based range.
- It ensures numeric:
  - `attrib.frameStart`
  - `attrib.frameEnd`
  - `attrib.handleStart` (default 0 if missing)
  - `attrib.handleEnd` (default 0 if missing)
- It writes these **back to the original matchmove version**, and copies them into
  the **plate version**.

This is what Nuke’s Load Clip expects and is why the plate now behaves like
any other AYON plate (frameStart/frameEnd are real numbers, not `None`).

Note: with the loader option “Start at workfile’s start frame” enabled in
Nuke, Read nodes will still be *offset* to start at the script’s first frame
even if the source sequence is 1001‑based—that is standard AYON Nuke loader
behaviour for all clips.

---

### 6. Summary

- Image Warp runs automatically and writes undistorted frames into a staging folder.
- Frames are renamed to AYON‑style names in **multi‑pass**, Windows‑safe fashion.
- The matchmove keeps an internal `undistorted_plate` representation pointing to the sequence.
- A `matchmoveMain_plate` product is created that **reuses** the same files and path.
- Version metadata (`frameStart`/`frameEnd`/handles) is normalized to a **1001‑based** range so Nuke’s Load Clip and other loaders treat the plate like any normal footage.

