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
  profile about its axis and set the anchor.
- **Joints**: where profiles on sketch edges meet, they butt against each other (one runs through, the
  others stop at its face) or miter. T-junctions are detected too. Joints follow sketch changes and
  profile size changes, so the cut list tells you "8 × 380, 4 × 470" without any manual trimming.
- **Section properties**: Ix, Iy, Wx and Wy of the modelled section, including closed faces and the
  weight class. For example, a 2040 standing on edge is 3.5× stiffer than lying flat.
- **Panels**: sheets that sit in the slots between profiles or cover the frame face (enclosure sides). You
  get the sheet size, area and mass, and a check that the sheet fits the slot. Density and thermal
  expansion follow the material (acrylic, polycarbonate, Dibond, glass, ...). A thermal check warns when a
  sheet in the slots would get too tight between its lowest and highest temperature, for example in a
  heated printer enclosure.
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
  - Each group gets a mark (A1, A2, ...), which also appears in the stock plan and in the tree's
    description column.
  - Objects with errors are listed at the top, and the total is marked incomplete.
  - The CSV export writes either decimal points with commas between fields, or decimal commas with
    semicolons, as used in many regions. It offers your system's format first.
  - Amounts use your system's currency symbol and number format; the currency can be set per document.

## Install

Link or copy this folder into your FreeCAD `Mod` directory, then restart FreeCAD:

```powershell
New-Item -ItemType Junction -Path "$env:APPDATA\FreeCAD\v1-1\Mod\ProfileBuilder" -Target (Get-Location)
```

Then pick **Profile Builder** from the workbench selector. Requires FreeCAD 0.21 or newer and has been
tested on 1.1.

## Usage

| Command | What it does |
|---|---|
| **Profile...** | Opens a task panel with a live preview. Uses the selected edges if there are any. |
| Series drop-downs | Inserts a catalog size straight away with your last-used length and style, placing it on the selected edges if there are any. |
| **Joints...** | Joins profiles on sketch edges wherever they meet, using the selected profiles or all of them. |
| **Panel...** | Creates a sheet in the opening between three or more selected profiles. |
| **Carriage...** | Adds a carriage on the selected profile (click the face it runs on) and shows its clear run and stroke. Select a solid as well to show it as the carriage. |
| **Pricing and stock...** | Prices, stock bar length, kerf, cutting, delivery and tax, with a live estimate. |
| **Cut list and costs** | Creates or updates the `Cut list` spreadsheet. |
| **Export cut list (CSV)** | Writes the same data to a CSV file. |

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
6. Set prices in **Pricing and stock** and create the **Cut list and costs**.

Joints need straight members. Butt joints need them to be perpendicular, and miter joints work where
exactly two profiles meet. The Joint object reports an error if a corner doesn't fit these rules.

To edit a profile, double-click it. Cancel undoes all changes. You can also use it from a macro:

```python
from freecad.profile_builder import feature
p = feature.make_profile("40-8", cols=1, rows=2, length=750, SlotStyle="V-slot", MiterEnd=45)
App.ActiveDocument.recompute()
```

## Accuracy

Dimensions are typical values for each slot system. Profiles are close to the real ones, but they are
not a manufacturer's drawing, and real extrusions differ by a few tenths of a millimetre from vendor to
vendor. The weight classes use generic rules (wall thickness scaled to the grid size) rather than a
specific vendor's profile, so their masses are estimates.
Mass is estimated from the modelled section, which is simplified, so it comes out a little heavy on the
large 40/45 sizes. The same applies to the section properties (Ix, Iy, W). Check the vendor datasheet
before relying on them. The expansion coefficients are typical values for each material, so the thermal
fit check is a rule of thumb.

## Roadmap

[docs/plans](docs/plans/README.md) holds the planned features, each with the problem it solves, a
proposal, an implementation approach checked against the code, and the effort.

## Development

- `python -m pytest tests`: catalog, stock and piece-identity tests, no FreeCAD needed
- `freecadcmd tests/freecad_smoke.py`: geometry, edges, miters, save/reload and cut list (run it from the repo root)
- `freecadcmd tests/freecad_linear.py`: carriages, clear run and stroke (also from the repo root)
- `freecadcmd tools/make_icons.py`: regenerates the toolbar icons from the real geometry
