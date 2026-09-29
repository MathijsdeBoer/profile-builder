# Mass, centre of gravity, tipping and foot loads

| | |
|---|---|
| Status | Planned |
| Category | Analysis |
| Effort | M (first estimate M) |
| Value | medium |
| Proposed from | engineering, industrial |

## Problem

Tall enclosures, machine stands, workstations and carts on castors can tip, and users need the per-foot load to choose levelling feet or castors. The report already sums mass for delivery, but ignores where the mass is and ignores the heavy payload: the machine or printer on the frame, tools, stored material, electronics.

## Proposal

Add a 'Mass point' object, a vertex with Mass and Label shown like the orange joint dot, for payloads such as 'Printer 12 kg' or 'Control cabinet 25 kg'. A Load can also reference one as a point load on a member.

Total mass and centre of gravity come from the profile solids (Shape.CenterOfMass in world coordinates), panels and mass points, and are shown as a marker. An optional per-joint hardware allowance (brackets, T-nuts, screws) makes the delivery weight more honest.

The support polygon is taken from the lowest profile ends, user-marked feet, or end-fitting positions. The 'Mass and balance' report block then gives:
- 'tips at 0.35 g sideways / a 120 N push at the top edge';
- CoG height and offset;
- the static load per foot, checked against the foot's rating.

## What exists today

Partly exists: every Profile and Panel has a Mass output, and build_report sums it into 'Delivery (x kg)'. There is no centre of gravity, no payloads and no support polygon. The Load objects that mass points are meant to feed do not exist.

## Implementation approach

Effort M confirmed.

The value depends on the frame. Small frames and enclosures on a bench rarely tip, and the payload guesses dominate the result. It matters for tall stands, workstations, machine bases and carts on castors, where the foot and castor ratings also have to be checked.

Implementation:
- New masses.py with a MassPoint class: Part::FeaturePython with a Part.Vertex shape, Mass and a note, and a view provider modelled on ViewProviderJoint in a different colour. It links to nothing, so there is no cycle risk.
- balance(doc):
  - sum obj.Mass x obj.Shape.CenterOfMass over valid profiles and panels (each Shape is a single Solid; use getGlobalPlacement when inside an App::Part), plus the mass points;
  - support polygon from profile shape vertices within 1 mm of the global minimum Z, or from fitted ends if end-fittings lands, via a 2D convex hull in pure Python;
  - tip ratio per hull edge = dist(CoG_xy, edge) / CoG_z;
  - push force at the top = m g d / H;
  - per-foot load from the rigid-body, equal-spring solution, labelled as an estimate.
- cutlist._blocks gets a 'Mass and balance' block, rounded to about 5 mm and 2 significant figures, plus an optional CoG marker.
- Feet and castors are rated in lb in imperial regions, so format mass, force and distance through FreeCAD's unit schema (Units.Quantity(...).getUserPreferred()) instead of hard-coding kg, N and mm.
- freecad_smoke: a symmetric cube has its CoG at the centre and equal foot loads; an offset mass point moves it.

## Blockers and caveats

- Profile masses are estimates (a little heavy on 40/45) and payloads are user guesses.
- Without end fittings, the support polygon is inferred from the lowest vertices, which is wrong for frames standing on feet or castors.

## Risks

- Profile masses are estimates, a little heavy on 40/45.
- Payload masses are user guesses and dominate the result, so round the CoG to about 5 mm and the tipping figures to 2 significant figures.
- Four feet are statically indeterminate, so give per-foot load as a range or a 'rigid, level floor' estimate.
- Mass points must not link into profiles in a way that creates cycles.

## Prior art

The FreeCAD wiki Macro_CenterOfMass for selected solids, without payloads or tipping. Vendor configurators give total weight only. Vendor catalogues list foot ratings.

## Modules

- new freecad/profile_builder/masses.py
- `cutlist.py`
- `panels.py`
- `feature.py`
- `fittings.py (support polygon, if end fittings exist)`
- `commands.py`
- `tests/freecad_smoke.py`
