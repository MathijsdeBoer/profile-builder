# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Profile Builder is a FreeCAD workbench (FreeCAD 1.0+, developed on 1.1; CI tests 1.0 and 1.1) that generates parametric
aluminium T-slot / V-slot extrusion profiles, joins them on sketch edges, adds sheet panels, and
produces cut lists, stock bar plans and cost estimates. See README.md for the user-facing features.

It is meant for a broad international audience: hobbyists and professionals, in metric and imperial
regions, buying from many suppliers. Don't build in regional defaults such as a currency, a number
format, a tax name, a supplier or metric-only units. Take them from the system locale
(`pricing.default_currency`, `pricing.format_money`) or FreeCAD's settings, or make them a setting.
Known gaps are in `docs/plans/international-units-and-formats.md`.

## Commands

pytest is not installed globally; run it through uv:

```bash
uvx pytest tests -q -p no:cacheprovider                              # pure-Python tests (catalog, stock)
uvx pytest tests/test_stock.py::test_kerf_can_force_an_extra_bar -q   # a single test
uvx --with numpy --with scipy pytest tests -q -p no:cacheprovider    # includes the frame solver tests
```

`tests/test_frame_model.py` is skipped when numpy and scipy are missing, which is the case with plain
`uvx pytest`.

The FreeCAD tests need FreeCAD's console. Run them from the repo root, because the script finds the
package through the working directory:

```bash
"/c/Users/MathijsdeBoer/AppData/Local/Programs/FreeCAD 1.1/bin/freecadcmd.exe" tests/freecad_smoke.py
"/c/Users/MathijsdeBoer/AppData/Local/Programs/FreeCAD 1.1/bin/freecadcmd.exe" tools/make_icons.py   # after catalog changes
```

- `freecad_smoke.py` prints `ok`/`FAIL` lines and ends with `N failure(s)`. It takes about 75 s,
  because it builds every catalog variant.
- Each feature has its own script in the same style: `tests/freecad_stiffness.py`,
  `tests/freecad_linear.py`, `tests/freecad_brackets.py`, `tests/freecad_panels.py` (panel fabrication,
  panel fit and stable piece marks) and `tests/freecad_check.py` (the frame check). The expected
  tracebacks are "Invalid profile dimensions" (stiffness), "no bracket part" (brackets) and "must lie
  parallel to the panel" (panels).
- Every FreeCAD script ends with `os._exit(1 if failures else 0)`. `freecadcmd` exits 0 when a script
  raises, so CI (`.github/workflows/tests.yml`, FreeCAD 1.0 and 1.1 AppImages) also requires the final
  `0 failure(s)` line. Keep both when adding a script, and add it to the workflow.
- FreeCAD 0.21 fails the sketch-edit tests (no topological naming), so `freecadmin` is 1.0.
- Linux AppImages can be tried locally in WSL: `--appimage-extract`, then
  `squashfs-root/AppRun freecadcmd tests/freecad_smoke.py`. Run `wsl.exe` from PowerShell; Git Bash
  rewrites `/mnt/c/...` paths.
- After changing any user-facing string, run `python tools/update_translations.py`;
  `tests/test_translations.py` fails while the template is out of date, or when a property tooltip is
  built at run time (an f-string or `+`): tooltips are looked up by their text, so write them as literals.
- Test scripts that create a `QApplication` set `QT_QPA_PLATFORM=offscreen` when Linux has no display
  (CI). It has to be set in the script: FreeCAD's AppRun overrides the variable.
- `freecadcmd` on Windows prints to a cp1252 console: a check message with a character outside it (₹, −)
  raises in `print` and stops the script. Wrap such values in `ascii()`.
- `freecadcmd` often prints each output line twice; filter with `awk '!seen[$0]++'`.
- A traceback about "Panel is too thick" is expected: that is a deliberate error case.
- The file name must not match `test_*.py` / `*_test.py`, or pytest will try to collect it.

To use a source tree without installing it, put it first on FreeCAD's namespace package, after
dropping any copy FreeCAD already loaded (see the top of `tests/freecad_smoke.py`):
`freecad.__path__.insert(0, "<tree>/freecad")`, with the `freecad.profile_builder*` entries removed from
`sys.modules` first.
- The main checkout is installed through a junction in FreeCAD's Mod folder, so FreeCAD loads it at
  startup. A plain `freecad.__path__.append(...)` in a worktree or an old checkout therefore silently runs
  the main checkout's code. The smoke test prints `testing <path>` and stops if the path is wrong.
- The GUI always loads the installed (main) copy, so GUI checks of a branch only work from the main
  checkout with that branch checked out.

- For GUI checks, run `freecad.exe script.py`. The script should drive steps with
  `QtCore.QTimer.singleShot`, write results to a log file, and end with `os._exit(0)`.
- Modal dialogs such as `QInputDialog.getItem` in the Joints command block the GUI; monkeypatch them in
  test scripts.
- To install for manual testing, link the repo into `%APPDATA%\FreeCAD\v1-1\Mod\ProfileBuilder` with a
  directory junction.

## Architecture

Layout: the package is a FreeCAD namespace package, `freecad/profile_builder/`. There is no
`freecad/__init__.py`. FreeCAD imports `__init__.py` at startup and `init_gui.py` in the GUI, which
registers the workbench. `package.xml` uses `<subdirectory>./</subdirectory>` for this layout.

The modules form layers, and the lower ones must stay importable without the GUI:

- **Catalog (`profiles.py`)**: pure Python, no FreeCAD imports, so pytest can load it directly.
  - Each `Series` holds the dimensions of one square cell. Multi-cell profiles (2040, 4080) tile cells.
  - `SERIES` is sorted by grid size, then slot width. Series keys like `"20-6"` are stored in saved
    documents, so never rename or remove a key.
  - Weight classes are rules in `apply_weight()`, not separate catalog entries. They must never change
    slot dimensions; a test enforces this.
  - `validate()` catches impossible geometry, both in tests and at recompute time.
- **Stock planner (`stock.py`)**: pure Python 1D cutting-stock (first/best-fit decreasing).
- **Other pure modules**:
  - `stroke.py`: clear-run, stroke and belt-length rules.
  - `metreware.py`: price parsing is pure; `report()` reads the document.
  - `frame_model.py`: a numpy/scipy 3D beam solver (mm, N, kg; tonnes internally), with no FreeCAD imports.
  - `fabrication.py`: flat sheet parts in 2D: rounded outlines, holes along slot lines (clipping,
    keep-outs, spacing), the fingerprint that groups identical sheets, and the DXF R12 and SVG writers.
- **Piece identity (`pieces.py`)**: pure Python. `canonical_cuts()` decides which pieces are identical
  by applying physical turns that keep the closed faces in place. It is why mirror-image miter pieces
  share a cut-list row. It also provides the `letters()` used for piece marks and spreadsheet columns.
- **Geometry (`geometry.py`)**: builds the 2D section as a single `Part.Face` by cutting slots, cavities,
  bores and chambers from a rounded rectangle, then extrudes it. Miters are cut with rotated boxes around
  the section-centre pivot.
  - `make_section` is LRU-cached and returns `.copy()`. Never hand out or modify the cached face itself.
  - Tests that time or compare sections call `clear_section_cache()`.
- **Document objects (`feature.py`, `joints.py`, `panels.py`, `pricing.py`)**: FeaturePython objects
  with view providers. `feature.Frame` / `member_frame()` gives a profile's world axes plus its section
  rectangle. Joints and panels use it for all placement maths.
- **Features on top of the frame**:
  - **Frame stiffness** (`frame_stiffness.py`, GUI in `frame_ui.py`) builds a beam model from the
    profiles and joints and solves it at a loose and a stiff joint bound.
  - **Carriages** (`linear.py`, GUI in `linear_ui.py`).
  - **Brackets** (`brackets.py`, GUI in `brackets_ui.py`): a link array of the user's part. `execute`
    only writes `ElementCount` and `PlacementList`, and never creates objects.
- **Frame check (`check.py`, GUI in `check_ui.py`)**: independent checks that return `Finding`
  records (severity, text, object names, optional fix). They never change the document; only
  `apply_fix` does, for deleting duplicates and joining ends. Overlaps are tested on each profile's
  outer box (`_envelope`: the section rectangle with the real length and miters), not on the slotted
  solid, which is slow and leaves slivers where butted faces touch.
  - A free end is measured to a nearby end of another profile, or to that end's joint, before an edge,
    so the join fix makes a corner rather than a T. An end that meets exactly is only reported when the
    outer boxes really overlap (collinear bars and hand-trimmed corners need no joint).
  - The duplicate fix keeps the copy that panels, carriages or brackets use, and offers no fix when
    more than one copy is in use.
- **Report (`cutlist.py`)**: `build_report(doc)` returns a `Report`. `_blocks()` turns it into the rows
  that both the spreadsheet and the CSV writer use.
  - Objects with errors go into `Report.errors`, shown as a block at the top, and the total is marked
    incomplete. Nothing may silently drop out of the list.
  - "Has an error" is `feature.problem(obj)`, not just `isValid()`. When something a profile depends on
    fails (a joint, a deleted sketch line), FreeCAD skips the profile but leaves it valid, with its old
    length; `problem()` catches that.
  - Pieces are compared on the upright section (`pieces.upright`: Rows >= Columns), so a 1x2 and a
    2x1 "on side" profile are the same product. `feature.product_key` names closed faces that way.
    Prices saved under the old key are found through `legacy_product_key`.
  - Callers run `recompute_if_needed(doc)` first.
  - Index rows through `PIECE_HEADER.index(...)`, not fixed positions.
  - Marks are stable. `build_report` reads the marks given so far from the document's `Piece marks`
    object (`cutlist.MarkStore`, JSON in an output property), `pieces.assign_marks` keeps each group's
    mark while its key exists, and `apply_marks()` stores the result. It also writes `PieceMark`, an output
    property on profiles and panels, so none of this triggers a recompute.
  - Carriages with a belt feed the "Metre ware" block, and placed brackets the "Hardware" block. A
    broken carriage or Brackets object goes into `Report.errors`. Stiffness results stay out of the cut
    list.
- **GUI (`commands.py`, `taskpanel.py`, `simple_panel.py`, `pricing_ui.py`)**: the GUI modules only.
  Every task panel opens a document transaction, applies changes live on a debounce timer, and
  implements Cancel as `abortTransaction()`.

### Invariants that are easy to break

- **Anchor and placement**:
  - `Shape.translate()` only sets a top-level location, and `Profile.execute` then overwrites it by
    restoring `obj.Placement`. So the anchor offset must be baked into the section face before
    extrusion (`make_section(..., anchor)`), never applied to the finished solid.
  - Profiles on a `PathEdge` compute their own Placement and Length in `execute`.
    `Length`/`Placement` (and `MiterStart`/`MiterEnd` when a joint controls that end) are then
    read-only outputs.
- **Joints must not create dependency cycles**:
  - Profiles link to a Joint (`StartJoint`/`EndJoint`), and the Joint never links back.
  - The joint finds its members through `InList`, and T-junction members through `PassingMembers`
    (names, not links). Its `Sources` links to the path objects, so sketch edits recompute it.
  - Trims are offsets from the sketch vertex, computed lazily in each profile's `execute` via
    `joints.adjustment()`.
  - Changing a property in `feature.SECTION_PROPS` calls `joints.touch_joints_of()`, so neighbours
    recompute.
  - Which profile runs through a butt joint is decided in this order: passing member, then the joint's
    `ThroughRule == "Manual"`, then the profiles' `JointRole`, then the rule. Ties are broken by
    direction (X, then Y, then Z), never by object name; name-based tie-breaking caused the
    "pinwheel" bug. Lines at equal angles to the axes (a frame turned 45°) are then told apart by
    their signed direction, flipped so the first non-zero component is positive, so neither the
    drawing direction nor the end decides.
  - A manual choice is stored by object name in `ThroughName`, because labels change. `Through` is
    only the label shown in the UI.
  - A joint-driven miter sets `StartMiterFromJoint` / `EndMiterFromJoint`, so the profile goes back to a
    square cut when the joint is removed. `MiterStartAxis` / `MiterEndAxis` record the axis each end was
    actually cut across; the cut list needs it to group pieces.
- **Backward compatibility of saved documents**:
  - `onDocumentRestored` calls `add_properties()`, which adds a property only if it is missing, and
    refreshes enumeration lists (Series, ThroughRule) while preserving their value.
  - All of this runs under a `_restoring` guard. Without the guard, a newly added `Weight` property
    would trigger `apply_series_defaults()` and wipe the user's customised dimensions.
  - Changing `Series` or `Weight` intentionally resets the dimensions.
  - `onChanged` handlers must return early while `feature.replaying(obj)` is true. Undo and Cancel
    (`abortTransaction`) write old values back with `Document.Transacting` set, and reacting to them
    (resetting dimensions, switching a joint to Manual) corrupts what they restore.
  - `tests/fixtures/legacy_<commit>.FCStd` are documents saved by older versions (8733122, the first,
    and ead3f7d). The smoke test opens each and compares with the stored results. Regenerate them only
    from a worktree of that commit with `make_legacy_fixture.py`, which refuses to run on current code.
- **Frame stiffness**:
  - Load the solver only through `frame_stiffness.solver()` (a lazy import), so the workbench and
    documents still load without numpy/scipy.
  - The settings object (`ProfileBuilderStiffness`, with the baseline as JSON) never links to profiles.
  - The frame is taken as Z-up: supports are the lowest nodes, loads act on the highest.
  - Joint springs come from geometry and the through rules, never from object names. At each joint the
    through profile is rigid and the others get springs of factor·E·I/L; a miter gets two springs of
    2·factor·E·I/L in series. Supports sit on the centre line of the profile standing on them.
  - Tests that call `App.Units.setSchema` must restore the original schema.
  - Some FreeCAD unit schemas have no units for moments, frequencies or stiffness; `unit_for` falls back
    to metric or imperial units there.
- **Carriages must not create cycles**:
  - A carriage links to its `Rail`, and through `Neighbours` (an `App::PropertyLinkListGlobal`, rewritten
    in `execute`) to the profiles and panels that reach its envelope, minus anything in its
    `InListRecursive`. It never writes to them.
  - `PropertyLinkListHidden` creates no dependency in FreeCAD 1.1, so don't switch to it.
  - `make_profile`/`make_panel` call `linear.touch_carriages(doc)`, and profiles and panels call
    `linear.member_moved` from `onChanged("Placement")`. Keep both hooks.
  - `obj.Shape` returns an immutable shape in FreeCAD 1.1: use `shape.transformed(matrix)` rather than
    setting its Placement. An offset that must survive assigning `obj.Placement` goes inside a compound.
- **Brackets**:
  - The Brackets object links to its Joints and to a hidden Members list; profiles and joints never
    link to it.
  - `SourceFrame` is in the part's own coordinates (`LinkTransform` is False, so the part's own
    Placement is ignored).
  - The type name "Fitting" is reserved for the planned feet and castors feature.
  - `joint_spots` returns `(placement, first, second, (corner key, label))`. Corner keys use object names,
    never labels; `SkippedCorners` holds keys, and a skipped corner stays listed in `Corners`. The End plate
    style has its own frame (`plate_frame`) and property list (`fields(obj)`), and only T-junctions.
- **Piece marks**:
  - The mark key is the `collect()` key as JSON. Changing that key (the product key, the rounding, the
    cut description) gives every group in existing documents a new mark.
  - Marks of vanished groups are retired, never reused. Only the Renumber command resets them.
  - Undo rolls back the `Assigned` property, so the marks given so far are also kept where undo cannot
    reach: on the MarkStore proxy (saved with the document) and in a per-document session cache (for an
    undo that removes the store itself). `mark_state` merges all three.
  - Sheet marks use the prefix `P-`. Profile marks never contain a hyphen, so the two cannot collide.
  - The 3D label lives under the view provider's `RootNode`, which already carries the placement, so its
    position is in local coordinates. The root node stays in the scene when the object is hidden, so the
    label's switch follows `Visibility` by hand.
- **Panel fabrication**:
  - Holes are clipped to the real outline (`fabrication.polygon_of`: rounded corners, non-convex
    shapes) and kept out of cutouts. Slot lines end where the face beside the slot really ends
    (`_face_extent` probes the solid), which matters at miters on wide flat profiles.
  - `Cutouts` is an `App::PropertyLinkGlobal`, and the sketch is used with its global placement, so a
    sketch in a Body or Part works. Older panels with a plain link are migrated in `add_properties`.
  - `panels.drawing()` is the single description of the flat part. The solid, the exported files, the
    hole count and the cut-list grouping all come from it, so they cannot disagree.
  - Holes, rounding and tolerance default to 0 for panels in opened older documents (`CutTolerance` is
    0.2 mm only for new panels), so their shapes and fit results do not change.
  - DXF R12 has no unit field: the unit goes in the file name and the MARK text. Keep DXF text ASCII.
- **Panel materials**: `panels.material_data` returns None for unknown or ambiguous names ("glass-clear
  PETG"). `Expansion == 0` means "not known", and the thermal check is then skipped rather than guessed.
- **Product keys**:
  - `Designation` (e.g. `"4040 Ultralight V-slot (40-8)"`) plus the closed faces
    (`feature.product_key`) is the key for prices, stock lengths and cut-list grouping.
  - Prices are stored per document in the `ProfileBuilderPricing` object, so changing the designation
    format orphans prices saved in existing documents.
  - User pricing defaults live in `<UserAppData>/ProfileBuilder/pricing.json`.
- **Translations**:
  - Command texts use the command name as the context (`QT_TRANSLATE_NOOP("ProfileBuilder_CutList", ...)`),
    because that is how FreeCAD looks them up. Property tooltips use `"App::Property"`, the workbench, its
    toolbars and menus `"Workbench"`, and panel texts `translate("ProfileBuilder", ...)`.
  - Never pass an f-string: translate a template and fill it in with `.format()`.
  - Never translate enumeration values or anything compared in code (Series, Mount, PurchaseMode, joint
    Type, ...). They are stored in documents.
- **FreeCAD and Qt quirks**:
  - In the Qt 5 bindings (FreeCAD 1.0), `QLocale.toCurrencyString(float, symbol)` picks an integer overload
    and `toString(float)` a single-precision one, so both lose cents. `pricing.money_in` builds the number
    from integers in the locale's own digits and takes only the symbol's position from the locale.
  - Don't give objects purely numeric labels like `"2040"`: FreeCAD makes a duplicate `"2041"`. That's
    why labels are `"2040 profile"`.
  - Qt's `findData` cannot match tuple item data, so combo boxes use string keys like `"1x2"`.

## Working in this repo

- On this Windows machine Python's default encoding is cp1252. Always pass `encoding="utf-8"` when a
  script rewrites source files; the sources contain `°`, `×`, `²` and `Ø`.
- Python replacement scripts in bash heredocs have mangled escapes: `"\n"` became a real line break,
  and `\b` in a regex became a backspace character. Prefer the Edit tool for such changes, and check
  for control characters after any scripted rewrite.
- The profile dimensions are approximate values, not vendor drawings (see README "Accuracy").
- Planned features are in `docs/plans/`, one file per feature with a status. Update its status and
  the index table when you implement or change one.
- The maintainer wants AI involvement recorded openly. Commits carry the `Co-Authored-By` trailer, and
  significant work should get a row in the timeline in `AI_DISCLOSURE.md`.
