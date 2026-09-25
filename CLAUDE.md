# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Profile Builder is a FreeCAD workbench (FreeCAD 0.21+, developed on 1.1) that generates parametric
aluminium T-slot / V-slot extrusion profiles, joins them on sketch edges, adds sheet panels, and
produces cut lists, stock bar plans and cost estimates. See README.md for the user-facing features.

## Commands

pytest is not installed globally; run it through uv:

```bash
uvx pytest tests -q -p no:cacheprovider                              # pure-Python tests (catalog, stock)
uvx pytest tests/test_stock.py::test_kerf_can_force_an_extra_bar -q   # a single test
```

The FreeCAD tests need FreeCAD's console. Run them from the repo root, because the script finds the
package through the working directory:

```bash
"/c/Users/MathijsdeBoer/AppData/Local/Programs/FreeCAD 1.1/bin/freecadcmd.exe" tests/freecad_smoke.py
"/c/Users/MathijsdeBoer/AppData/Local/Programs/FreeCAD 1.1/bin/freecadcmd.exe" tools/make_icons.py   # after catalog changes
```

- `freecad_smoke.py` prints `ok`/`FAIL` lines and ends with `N failure(s)`. It takes about 75 s,
  because it builds every catalog variant.
- `freecadcmd` often prints each output line twice; filter with `awk '!seen[$0]++'`.
- A traceback about "Panel is too thick" is expected: that is a deliberate error case.
- The file name must not match `test_*.py` / `*_test.py`, or pytest will try to collect it.

To use the source tree without installing it, extend FreeCAD's namespace package before importing:
`import freecad; freecad.__path__.append("<repo>/freecad")`.

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
- **Geometry (`geometry.py`)**: builds the 2D section as a single `Part.Face` by cutting slots, cavities,
  bores and chambers from a rounded rectangle, then extrudes it. Miters are cut with rotated boxes around
  the section-centre pivot.
- **Document objects (`feature.py`, `joints.py`, `panels.py`, `pricing.py`)**: FeaturePython objects
  with view providers. `feature.Frame` / `member_frame()` gives a profile's world axes plus its section
  rectangle. Joints and panels use it for all placement maths.
- **Report (`cutlist.py`)**: `build_report(doc)` returns a `Report`. `_blocks()` turns it into the rows
  that both the spreadsheet and the CSV writer use.
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
    "pinwheel" bug.
- **Backward compatibility of saved documents**:
  - `onDocumentRestored` calls `add_properties()`, which adds a property only if it is missing, and
    refreshes enumeration lists (Series, ThroughRule) while preserving their value.
  - All of this runs under a `_restoring` guard. Without the guard, a newly added `Weight` property
    would trigger `apply_series_defaults()` and wipe the user's customised dimensions.
  - Changing `Series` or `Weight` intentionally resets the dimensions.
- **Product keys**:
  - `Designation` (e.g. `"4040 Ultralight V-slot (40-8)"`) plus the closed faces
    (`feature.product_key`) is the key for prices, stock lengths and cut-list grouping.
  - Prices are stored per document in the `ProfileBuilderPricing` object, so changing the designation
    format orphans prices saved in existing documents.
  - User pricing defaults live in `<UserAppData>/ProfileBuilder/pricing.json`.
- **FreeCAD and Qt quirks**:
  - Don't give objects purely numeric labels like `"2040"`: FreeCAD makes a duplicate `"2041"`. That's
    why labels are `"2040 profile"`.
  - Qt's `findData` cannot match tuple item data, so combo boxes use string keys like `"1x2"`.

## Working in this repo

- On this Windows machine Python's default encoding is cp1252. Always pass `encoding="utf-8"` when a
  script rewrites source files; the sources contain `°`, `×`, `²` and `Ø`.
- Python replacement scripts in bash heredocs have turned `"\n"` escapes into real line breaks; prefer
  the Edit tool for such changes.
- The profile dimensions are approximate values, not vendor drawings (see README "Accuracy").
- The maintainer wants AI involvement recorded openly. Commits carry the `Co-Authored-By` trailer, and
  significant work should get a row in the timeline in `AI_DISCLOSURE.md`.
