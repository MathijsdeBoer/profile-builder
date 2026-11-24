# Box frame generator sized by outside, inside or centre-line dimensions

| | |
|---|---|
| Status | Partly done |
| Category | Design & modelling |
| Effort | L (first estimate M) |
| Value | high |
| Proposed from | printer-builder, industrial, freecad-ux, competitors |

## Problem

Printer frames, enclosures, workbenches, machine bases and guard frames are nearly always a box with a few extra rails. Today each one takes two or three hand-drawn sketches, then inserting profiles, running Joints and adding panels. Users think in outside or clear-inside sizes ("600x600x700 outside", "a 350 mm printer plus 30 mm clearance", "a bench that fits a 1200 mm alcove"), but the workbench works from centre lines. A 400 mm centre-line cube in the smoke test comes out 420 mm outside, so users subtract the profile size by hand, and do it again after switching 2020 to 3030 or to 2040 posts. Changing the size means editing several sketches and keeping them consistent.

## Proposal

Add a 'Frame skeleton' Part::FeaturePython whose Shape is a compound of lines in a fixed, documented edge order: the 12 base edges first, extras appended. Profiles then attach through PathEdge and joints through Sources, exactly as they do with sketches. Properties:
- Width, Depth, Height, and SizeMode (Outside / Inside clear / Centre lines);
- its own post and rail section-size properties, used for the inset;
- mid-rails at listed heights (bed or Z-motor rails, a shelf, a worktop support), OpenTop/OpenBottom, extra posts;
- template type (cube, open-top enclosure, table with legs).
Every property can be bound by expression, for example to a 'Params' spreadsheet with BedX, BedY and Clearance for a printer, or the footprint of the machine a frame must hold.

A 'Box frame...' task panel creates everything in one transaction, with a live summary such as '8 x 380, 4 x 420': the skeleton, the profiles (separate series for posts and rails, JointRole preset), joints via create_joints with the chosen rule, and optional panels (in slot or on face) on chosen sides. Changing Width, or switching 2020 to 3030, re-derives the centre lines so the outside size stays what the user typed. The smoke test's hand-built cube becomes a one-liner.

Second stage: more generators (guard fence with N bays, ladder/conveyor frame with cross members at a pitch). 'Save as template' writes a frame and its spreadsheet aliases to <UserAppData>/ProfileBuilder/templates/*.FCStd, and 'Insert template' merges one into the active document, asking for the parameter values.

## What exists today

- `skeleton.py` provides a `Part::FeaturePython` skeleton with stable edge order: bottom edges 1-4,
  top edges 5-8, posts 9-12.
- `Box frame...` creates a closed cube, with outside, inside-clear and centre-line sizing, separate
  post and rail series/sizes, vertical butt joints and a live cut-length summary.
- The skeleton derives its insets from the attached profiles, per side, so changing a section (also on one
  side only) keeps the requested outside or inside-clear dimensions. Profile size changes touch the
  skeleton without adding a link cycle.
- A section offset (Align slots), an anchor, a spin or a changed joint rule can still change the size. The
  Check frame command compares `skeleton.measured_size()` with the requested size and warns when they
  differ by more than 0.01 mm.
- Rails wider than the posts in both directions would collide at the corners (`skeleton.rails_collide()`),
  so `make_box` and the panel refuse them before creating anything.
- A skeleton with an error puts its profiles in the cut list's error block (`feature.problem()` checks the
  path object and the joint sources).
- The panel keeps the exact value of each size field until its text is edited, and reads a bare number in
  the unit the field shows, so sizes do not drift in imperial unit schemas.
- The smoke test now builds the centre-line cube through the generator and checks the outside-sized
  cube at 2020 and 3030 post sizes.

The first stage is deliberately cube-only. Open faces, mid-rails, extra posts, panels, other frame
templates and saving/inserting templates remain future work.

## Implementation approach

Revised effort L, up from M, for the full proposal minus templates. The M first stage is implemented:
a live-preview dialog creates the cube in one transaction, supports three size modes and mixed post and
rail sections, and keeps the edge references stable. The remaining L-stage work is open-top/open-bottom
frames, mid-rails and extra posts, optional panels, other generator types, and templates. Templates are a
separate L.

Implementation:
- New skeleton.py with a Skeleton class (Part::FeaturePython, Type 'ProfileBuilder::Skeleton') using the same add()/add_properties/_restoring pattern as feature.Profile.
- execute returns Part.makeCompound([Part.makeLine(...)]) in a fixed order: Edge1-4 bottom, Edge5-8 top, Edge9-12 posts, then mid-rails appended in blocks of 4 per listed height. Separately made lines are not merged, so the EdgeN index is the list order.
- Always emit all 12 base edges, even with OpenTop, so indices never shift. The generator simply puts no profiles on the unused edges.
- SizeMode: centre = outside - post width (X/Y) and outside - rail height (Z). This assumes the Vertical rule with ExtendThrough and Anchor Center, which is what joints.adjustment gives today; Inside = centre - post width.
- To avoid the size-drift risk: instead of its own PostSize/RailSize properties, the skeleton can read CellSize/Columns/Rows/Spin of the profiles in its InList, like joints.ends_of does. These are input properties that apply_series_defaults sets in onChanged, before recompute. Posts are identified by PathEdge 'Edge9'..'Edge12'.
- Extend joints.touch_joints_of (or Profile.onChanged for SECTION_PROPS) to touch a Skeleton PathEdge owner. There is no link, so no cycle. Keep fallback size properties for when no profiles are attached yet.
- New 'Box frame...' command in commands.py, registered in init_gui.py. The task panel follows ProfileTaskPanel (openTransaction, debounce timer, abortTransaction on Cancel) and creates:
  - the skeleton;
  - make_profile per used edge, posts with JointRole 'Runs through';
  - joints via create_joints;
  - optional panels.make_panel(doc, [2 posts, 2 rails], Mount=...) per chosen side, with the members known from edge indices.
- Live summary from cutlist.collect restricted to the new objects. A Regenerate command handles count changes, because execute cannot add objects.
- freecad_smoke tests: 600x600x700 outside with 2020 stays 600 after switching the posts to 3030; Edge9 is the post at the origin after toggling OpenTop.

## Blockers and caveats

No hard blocker.
- The outside size assumes the Vertical rule with ExtendThrough on and Center anchors. A Swap joint, Manual rule or JointRole change alters the real outside, so the skeleton should compare against the actual bounding box and warn.
- Parameters that change a count need a Regenerate step.
- The catalog has metric series only. Width, Depth and Height accept inch input through FreeCAD's units, but a frame of inch profiles such as 80/20's 1010 or 1515 needs those series in the catalog, or a custom section, first.
- Template insertion via mergeProject renames objects. That breaks PassingMembers (names) and a Manual Joint.Through (labels), and duplicates the ProfileBuilderPricing singleton, so defer templates.

## Risks

Effort M covers the skeleton and the box generator. Template save/insert adds roughly a week.
- The skeleton reads profile sizes through its InList without linking back to them. Changes to anchors, joint rules or other nonstandard layouts can still alter the physical bounds, so the task panel compares measured and requested dimensions and warns when they differ.
- The edge order must never change between versions or when options are toggled (append only), or the PathEdge 'EdgeN' links jump to other edges.
- Three-member corners depend on the Vertical through-rule.
- Parameters that change a count (bays, cross members) cannot add objects during recompute, so they need a Regenerate command.
- Merging a template renames objects. That breaks PassingMembers (object names) and a Manual Joint.Through (a label), and can collide with the ProfileBuilderPricing singleton, so insertion must remap all three.

## Prior art

Online 2020 cube calculators. Motedis table configurator (table shapes, profile, connector type, feet and dimensions, giving a priced cart). Misumi FRAMES design templates. Bosch Rexroth MTpro and item Engineeringtool frame and guard assistants. FrameForge has no generators; it is sketch-driven only.

## Modules

- new freecad/profile_builder/skeleton.py
- `commands.py`
- `init_gui.py`
- `joints.py (reuse create_joints)`
- `panels.py (reuse make_panel)`
- `simple_panel.py or a new task panel`
- `tests/freecad_smoke.py`
- `tools/make_icons.py`
- `README.md`
