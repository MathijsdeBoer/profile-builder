# Profile Builder for FreeCAD

A FreeCAD workbench for designing and generating standard aluminium T-slot and V-slot
extrusion profiles (2020, 2040, 3030, 4040, 4080, 4545, 8080, ...) as parametric objects.

> **AI-generated code:** most of this project was written by Anthropic's Claude Opus 5.5 model,
> working as a coding agent in Claude Code, directed and tested by a human. See
> [AI_DISCLOSURE.md](AI_DISCLOSURE.md) for how it was used, the dates, and what it means for the
> accuracy of the profiles.

## Features

- **Catalog**, grouped by slot system:

  | Grid | B-type (Bosch Rexroth compatible) | I-type (item compatible) | Misumi |
  |---|---|---|---|
  | 15 | | | slot 3 |
  | 20 | slot 6 | slot 5 | |
  | 30 | slot 8 | slot 6 | |
  | 40 | slot 10 | slot 8 | |
  | 45 | slot 10 | slot 8 | |

- **Weight classes**: Standard, Light, Ultralight and Heavy for every series. The slot stays the same,
  so nuts and connectors fit. Light adds hollow corner chambers. Ultralight has thinner chamber walls
  and a large core bore that can't be tapped. Heavy has solid corners.
- **Any size**: tile 1–20 cells per direction (2040, 2080, 4080, 80160, ...). Profiles made of several
  cells get internal chambers and extra bores.
- **Variations**: T-slot or V-slot, closed faces (presets for 1/2/3-slot profiles), centre bore and corner
  chambers on or off.
- **Custom dimensions**: every section dimension is copied from the series onto the object, so you can
  change it to match a specific manufacturer.
- **Miter cuts** at either end, with the saw (tip-to-tip) length computed for you.
- **Frames from sketches**: select straight edges or a whole sketch and you get one profile per edge.
  Each profile follows its edge when the sketch changes. You can extend or trim either end, spin the
  profile about its axis and set the anchor. The **Align slots** tool can shift a section in local X/Y
  without moving its sketch edge.
- **Box frame generator**: make a closed cube from outside, inside-clear or centre-line dimensions, with
  separate post and rail profiles. Changing the dimensions or section sizes updates the skeleton and its
  joints. This first stage generates cubes; open faces, mid-rails, panels and saved templates are not
  included yet.
- **Joints**: where profiles on sketch edges meet, they butt against each other (one runs through, the
  others stop at its face) or miter. T-junctions are detected too. Joints follow sketch changes and
  profile size changes, so the cut list tells you "8 × 380, 4 × 470" without any manual trimming.
- **Align slots**: Ctrl-select the inside (floor) of one slot on each of two profiles and activate the tool.
  The profile you picked first slides along its section until its slot lines up with the second slot, the
  way two slots meet at a butt joint. No joint is needed, nothing is confirmed, and sketch edges, spin and
  length stay as they are; the section offset is saved and the change is one undo step. The two profiles
  must be square to each other, so a turned profile asks you to set its Spin first.
- **Brackets**: your own bracket part, for example a STEP file from your supplier, is placed in every
  square corner of the butt joints, one per slot that lines up on both profiles. Pick the bracket's two
  faces that touch the profiles once, and the brackets follow sketch edits, joint swaps and size
  changes. The cut list counts them, with the article number you type in. Miter corners get none yet.
- **Section properties**: Ix, Iy, Wx and Wy of the modelled section, including closed faces and the
  weight class. For example, a 2040 standing on edge is 3.5× stiffer than lying flat.
- **Panels**: sheets that sit in the slots between profiles or cover the frame face (enclosure sides). You
  get the sheet size, area and mass, and a check that the sheet fits the slot. Density and thermal
  expansion follow the material (acrylic, polycarbonate, Dibond, glass, ...). The fit checks (see
  [Panel fit](#panel-fit)) warn when a sheet in the slots gets too tight when hot or could come out when
  cold, and when the screw holes of a sheet on the face leave too little play.
- **Panel fabrication**: sheets on the face get mounting holes on the slot centre lines, evenly spaced,
  clear of the corners and joints where brackets sit, and a minimum distance from the edge. Where a face
  has two slots (a 2040 lying flat) you pick the outer, the inner or both. Corners can be rounded, and a
  sketch parallel to the sheet adds cutouts (fans, cable glands). **Export panels** writes a DXF and an
  SVG per different sheet for laser cutting or CNC routing, in mm or inches, with the mark, material and
  size in the file name and as text on a separate layer. The cut list counts the holes and lists a screw
  and slot nut for each.
- **Linear axis carriage**: a carriage that runs along a profile face, shown as a placeholder block or as
  your own model (for example a STEP file). It finds what really blocks it: posts at the rail ends, a
  T-junction member on its face, a panel in its slot, or objects you list. Members that butt against
  another face don't count, unless the carriage wraps around that face. You get the clear run and the
  usable stroke (the run minus the carriage and its end stops), and a warning when the stroke drops
  below what the axis needs, for example after changing the posts from 40 to 45. The position is set in
  percent or as a distance, and can be driven by an expression; what rides on the carriage, such as a
  gantry beam standing on it, can follow it by an expression too. For a belt drive you get the length of the
  open belt, rounded up to whole teeth, and the cut list lists it as metre ware.
- **Pricing**: price per metre per product and per m² per sheet, metre ware such as belts per metre or
  per foot, cutting cost, delivery (flat, per kg, free above an order value) and tax. The prices are stored
  in the document and can be saved as your defaults.
- **Stock bars**: pieces are packed into stock bars (with saw kerf and end trim) and you get a cutting plan
  per bar, or you can price the order as cut to size.
- **Cut list and costs**: a spreadsheet or CSV with the pieces, stock plan, sheets and cost summary.
  - Identical pieces are grouped even when they were drawn in opposite directions.
  - Each group gets a mark (A1, A2, ...), and each different sheet one too (P-1, P-2, ...). Marks
    appear in the stock plan, the tree's description column and, with **Show piece marks**, in the 3D
    view. They stay put when other pieces change: a changed piece gets a new number and old numbers are
    not reused, so labels already on pieces stay right. **Renumber piece marks** closes the gaps.
  - Sheets are the same part when their outline, holes and cutouts match, also turned or flipped over.
  - Objects with errors are listed at the top, and the total is marked incomplete.
  - The CSV export writes either decimal points with commas between fields, or decimal commas with
    semicolons, as used in many regions. It offers your system's format first.
  - Amounts use your system's currency symbol and number format; the currency can be set per document.
- **Check frame**: one list of what would otherwise pass silently. It covers profiles and panels with
  errors, profiles that overlap, and ends that meet or nearly meet another profile but have no joint (a
  sketch vertex a few tenths of a millimetre off). It also finds two profiles on the same sketch edge,
  panel fit problems, carriage warnings, pieces longer than a stock bar, lengths that differ by less than
  a millimetre, and sketch edges without a profile. Clicking a finding selects its objects, and the two
  obvious repairs (delete a duplicate, join ends) are one click. The cut list mentions any issues it
  finds.
- **Frame stiffness (estimate)**: sideways and twist stiffness at the top of the frame and its first
  natural frequencies, from a beam model of the profiles and joints. Joint stiffness is not known, so
  every value is a range between loose and rigid joints. Store a baseline to compare design variants
  (for example "1.1–1.9× stiffer, +1.0 kg"). Values follow FreeCAD's unit schema.

## Install

Link or copy this folder into your FreeCAD `Mod` directory, then restart FreeCAD:

```powershell
New-Item -ItemType Junction -Path "$env:APPDATA\FreeCAD\v1-1\Mod\ProfileBuilder" -Target (Get-Location)
```

Then pick **Profile Builder** from the workbench selector. Requires FreeCAD 1.0 or newer (0.21 lacks the
topological naming that keeps profiles on the right sketch edge). Tested on 1.0 and 1.1.

## Usage

| Command | What it does |
|---|---|
| **Profile...** | Opens a task panel with a live preview. Uses the selected edges if there are any. |
| Series drop-downs | Inserts a catalog size straight away with your last-used length and style, placing it on the selected edges if there are any. |
| **Joints...** | Joins profiles on sketch edges wherever they meet, using the selected profiles or all of them. |
| **Align slots** | Ctrl-select one slot floor on each of two profiles; the first profile slides so its slot lines up with the second's. Works with or without joints. |
| **Panel...** | Creates a sheet in the opening between three or more selected profiles. |
| **Carriage...** | Adds a carriage on the selected profile (click the face it runs on) and shows its clear run and stroke. Select a solid as well to show it as the carriage. |
| **Brackets...** | Places your bracket part in the corners of the joints. Pick its two contact faces first: the one on the profile that ends at the joint, then the one on the profile it meets. |
| **Calibrate bracket** | Sets again how the bracket sits, from its two contact faces picked on a placed bracket or on the part. |
| **Pricing and stock...** | Prices, stock bar length, kerf, cutting, delivery and tax, with a live estimate. |
| **Cut list and costs** | Creates or updates the `Cut list` spreadsheet. |
| **Export cut list (CSV)** | Writes the same data to a CSV file. |
| **Export panels (DXF/SVG)** | Writes a DXF and an SVG file for each different sheet into a folder. The unit follows FreeCAD's unit system. |
| **Show piece marks** | Shows or hides the marks in the 3D view, on the selected profiles or all of them. |
| **Renumber piece marks** | (menu only) Numbers all pieces again from A1. Labels printed earlier no longer match. |
| **Check frame...** | Lists problems in the frame by severity; click one to select its objects, and fix duplicates and unjoined ends. |
| **Frame stiffness...** | Estimates sideways and twist stiffness and natural frequencies, as a range between loose and stiff joints, and compares with a stored baseline. |

### Frame workflow

1. Draw the frame as lines along the profile centres. A cube needs two sketches (bottom and top) plus
   the posts, for example a third sketch in a vertical plane or any object with straight edges.
2. Select the sketches and insert a profile size. You get one profile per edge.
3. Run **Joints...** and pick a style. By default, vertical profiles run through and the rails butt
   against them.
4. Choose which profiles run through:
   - **Run through**: select the profiles that should stay long (for example two opposite sides of a
     square) and click it. The profiles they meet are trimmed instead. This sets each profile's
     `JointRole` (Auto / Runs through / Butts), which you can also set yourself.
   - **Swap joint**: select a joint (the orange dot), or a profile to swap both of its ends, and the other
     profile runs through that corner.
   - Double-click a joint, or select several and use the property editor, to set `Type` (Butt/Miter),
     `ThroughRule`, `Through`, `ExtendThrough` and `Gap`.

   When profiles are equally long, direction decides (X before Y before Z), so a square comes out
   as 2 long and 2 short sides.
5. Optionally select the four profiles around an opening and add a **Panel**.
6. Optionally import your corner bracket (File > Import, e.g. a STEP file), pick its two faces that touch
   the profiles and click **Brackets**. `Rule` decides whether a T-junction gets brackets on both sides or
   only on the sides facing into the frame, so not on a stub such as a post standing out above a rail.
   `SwapLegs` turns brackets with unequal legs, and `SlotOffset` moves a bracket whose slot key is
   off-centre.
7. Set prices in **Pricing and stock** and create the **Cut list and costs**.

Joints need straight members. Butt joints need them to be perpendicular, and miter joints work where
exactly two profiles meet. The Joint object reports an error if a corner doesn't fit these rules.

To edit a profile, double-click it. Cancel undoes all changes. You can also use it from a macro:

```python
from freecad.profile_builder import feature
p = feature.make_profile("40-8", cols=1, rows=2, length=750, SlotStyle="V-slot", MiterEnd=45)
App.ActiveDocument.recompute()
```

### Panel fit

The fit checks compare the sheet with the aluminium frame between the assembly temperature and the
lowest and highest temperature in use. What they assume:

- Only the difference counts, because the frame expands too (23 µm per m per kelvin). Acrylic expands
  about three times as much, so a 600 mm acrylic sheet fitted at 20 °C grows 0.85 mm more than its frame
  at 50 °C. Glass and wood expand less than aluminium, so they shrink against the frame when warm.
- **Hot, in the slots**: the growth plus the cut tolerance must fit in the gaps at the slot bottoms on
  both sides together. That holds wherever the sheet sits, even when a standing panel rests on its lower
  edge, as long as it can slide. A sheet that is glued, clamped or pressed in by a stiff seal cannot slide
  and bows instead.
- **Cold, in the slots**: the sheet shrinks, may be cut undersize, and can rest against the far slot.
  What is left in the slot must reach past the slot lips. For glass, wood or steel this happens when the
  frame is warmest, because they expand less than aluminium. A large Clearance helps when hot but hurts
  here, so the two checks together bound it. When no Clearance or InsertDepth passes both, the check says
  so once instead of sending you back and forth: the sheet then needs deeper slots, a smaller or split
  sheet, a narrower temperature range, or mounting on the face.
- **On the face**: screws hold the sheet, so it grows around its centre, and the farthest holes move
  most. The holes need that much play around the screws. Oversize holes (and washers) let the sheet move;
  tight holes crack acrylic. If one hole is a snug locating hole instead, the sheet grows from there, and
  with that hole in a corner the far holes need about twice the play.
- **Cut tolerance** (±) is part of the budget: a laser or CNC cut is typically within 0.1-0.2 mm, a saw
  within 0.5-1 mm.
- The temperatures are those of the sheet, not the air. A sheet in a heated enclosure runs cooler than
  the air inside, and a dark sheet in the sun much warmer than the air outside. The expansion
  coefficients vary by grade (cast or extruded acrylic, for example), so the results are rounded rules of
  thumb. Wood and MDF move more with humidity than with temperature; that is not checked. Temperatures
  are in °C for now.

## Accuracy

Dimensions are typical values for each slot system. Profiles are close to the real ones, but they are
not a manufacturer's drawing, and real extrusions differ by a few tenths of a millimetre from vendor to
vendor. The weight classes use generic rules (wall thickness scaled to the grid size) rather than a
specific vendor's profile, so their masses are estimates.
Mass is estimated from the modelled section, which is simplified, so it comes out a little heavy on the
large 40/45 sizes. The same applies to the section properties (Ix, Iy, W). Check the vendor datasheet
before relying on them. The expansion coefficients are typical values for each material, so the thermal
fit check is a rule of thumb. The frame stiffness is an estimate for comparing designs. It assumes a
joint stiffness range and a rough torsion constant, and panels add mass but no bracing. T-nut slip,
belts, drives and the floor are not modelled.

## Roadmap

[docs/plans](docs/plans/README.md) holds the planned features, each with the problem it solves, a
proposal, an implementation approach checked against the code, and the effort.

## Development

- `python -m pytest tests`: catalog, stock and piece-identity tests, no FreeCAD needed
- `uvx --with numpy --with scipy pytest tests`: also runs the frame solver tests (skipped without numpy/scipy)
- `freecadcmd tests/freecad_smoke.py`: geometry, edges, miters, save/reload and cut list (run it from the repo root)
- `freecadcmd tests/freecad_stiffness.py`: the frame stiffness estimate against closed forms, baseline and units
- `freecadcmd tests/freecad_linear.py`: carriages, clear run and stroke (also from the repo root)
- `freecadcmd tests/freecad_brackets.py`: bracket calibration and placement, on the 400 mm cube and more
- `freecadcmd tests/freecad_panels.py`: panel fabrication, panel fit and stable piece marks
- `freecadcmd tests/freecad_check.py`: the frame check
- `freecadcmd tests/freecad_slot_alignment.py`: profile slot alignment by picked slots and at butt joints
- GitHub Actions runs all of these on every push, on FreeCAD 1.0 and 1.1 (`.github/workflows/tests.yml`).
  The FreeCAD scripts exit non-zero when a check fails.

### Translating

User-facing strings are marked for translation: command texts with the command name as context,
property tooltips with `App::Property`, and panel texts with `ProfileBuilder`.
`python tools/update_translations.py` collects them into
`freecad/profile_builder/resources/translations/ProfileBuilder.ts` (pure Python, no Qt tools needed).
To add a language, run it with `--add` and FreeCAD's code for the language (for example `de`, `fr`, `es-ES`,
`pt-BR`, `sv-SE` or `zh-CN`; FreeCAD loads no other suffix), translate the `.ts` file in Qt Linguist,
and compile it with `lrelease` (or `pyside6-lrelease`) into a `.qm` file next to it. FreeCAD picks it up
when it runs in that language. Values that are stored in documents, such as the series, mount and joint
type names, stay in English on purpose. Messages in the report view and the cut list are not translated
yet.
- `freecadcmd tools/make_icons.py`: regenerates the toolbar icons from the real geometry
