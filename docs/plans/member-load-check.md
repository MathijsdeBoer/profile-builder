# Deflection and stress check per member, shown as a range between support bounds

| | |
|---|---|
| Status | Planned |
| Category | Analysis |
| Effort | M (first estimate M) |
| Value | medium |
| Proposed from | printer-builder, competitors, engineering |

## Problem

Builders want to know whether a 600 mm 2020 rail will carry a 5 kg spool holder or a shelf without visible sag, whether a workbench or workstation beam takes its load, and whether a gantry beam on a 3D printer or CNC router is stiff enough. Vendor calculators need the span and I values retyped and assume ideal supports, while T-slot joints are somewhere between pinned and fixed.

## Proposal

Add a Load object, a FeaturePython linked to one profile the way Joint links work, or a 'Deflection' section in the profile task panel. Inputs:
- Type: point, distributed, mass on member, or self-weight only;
- magnitude in N or kg, position along the member, direction (gravity or local X/Y);
- span, defaulting to the profile length.
The support condition is inferred from StartJoint/EndJoint. Joints at both ends give a range from simply supported to fixed-fixed, and a joint at one end gives a cantilever. Self-weight, and a share of each panel's mass (panels.Profiles says which members carry it), are added automatically. Gravity is projected onto the principal axes from member_frame, which handles Spin. The inputs use unit-carrying properties (App::PropertyForce, App::PropertyLength), so an imperial unit schema shows lbf and inches without extra code.

The maths lives in a pure-Python beams.py, tested with pytest. It gives deflection, span/deflection ratio, bending stress against a 6063-T6 yield (about 170 MPa, editable), and the payload natural frequency f ≈ 15.8/√δ[mm] Hz, which matters for vibration in gantries and machines (ringing and input shaping on 3D printers). Example with the modelled 2020: a 600 mm span with 50 N at mid-span deflects 0.11-0.44 mm depending on joint fixity, at only about 10 MPa. That shows deflection, not strength, is what matters.

Verdicts are words ('comfortable', 'check', 'likely too flexible') against an editable limit such as L/500, with the assumptions listed. Results go in Info properties, the task panel and a 'Checks' block in the report, and members over the limit can optionally be coloured. A document-level 'Engineering settings' object (E = 69 GPa, yield, safety factor, deflection limit) is shared with the other analysis features. Yield must be editable because vendors use different alloys (EN AW-6063 T66 at item, 6105-T5 at 80/20).

## What exists today

The section properties this needs now exist: every profile has Ix, Iy, Wx and Wy of the modelled section (see [section properties](section-properties.md)). They come from Part.Face.MatrixOfInertia: the probe measured 2020 Ixx = Iyy = 7412 mm⁴ (about 0.74 cm⁴) and 2040 50920 / 14579 mm⁴. The proposal's example holds with these values: 50 N at mid-span of 600 mm deflects about 0.12-0.47 mm, at about 10 MPa.

## Implementation approach

1. feature.py: add read-only Info outputs Ixx, Iyy, Wx and Wy through add_properties, computed in execute from face.MatrixOfInertia (the face is already built there). This is the S part and is reusable.
2. beams.py (pure, pytest):
   - Closed-form point, UDL and cantilever cases for pinned-pinned and fixed-fixed.
   - Bending stress, span/deflection ratio, and f ≈ 15.76/√δ[mm].
   - A shear note when L/h < 10.
3. loads.py: a Load FeaturePython with a PropertyLink to one profile (the profile never links back). It has Type, Magnitude, Position and Direction. execute writes the deflection range and a verdict to read-only strings.
   - Supports come from StartJoint and EndJoint.
   - A passing member is split at the vertices of joints whose PassingMembers list it.
   - Self-weight comes from MassPerMeter, the panel share from panels whose Profiles include it, and gravity is projected with member_frame.
4. Put E, yield and the deflection limit in a small 'Engineering' settings object, not in pricing.Settings.
5. cutlist: a Checks block. taskpanel: an optional Deflection info line.

## Blockers and caveats

- The core of the workbench is cut lists, lengths and cost. A load check is a second step, and vendor datasheet Ix/Iy values are not in the catalog, so it relies on the modelled section.
- In machine frames such as 3D printers and CNC routers, joint slip and toolhead dynamics usually matter more than static member deflection. Static deflection is the main question for shelves, workbenches and long spans. Vendor calculators already cover the simple single-member cases.
- Worth doing only after the manufacturing items. The Ixx/Iyy outputs alone are a cheap add-on.

## Risks

- Depends on section-properties.
- Users may read a single number as the truth; always showing the pinned-to-fixed range and the assumptions prevents that.
- Closed-form cases don't cover multi-span members (a passing member through a T-junction). Treat each segment as simply supported.
- Shear deformation matters when L/h < 10, which should add a note.
- In bolted frames, joint flexibility often dominates.
- The Load links to the profile, and the profile never links back.

## Prior art

80/20, Vention, item, Bosch Rexroth (MTpro) and Misumi deflection calculators use the same closed-form formulas, but the profile and span must be retyped. FrameForge has no load checks.

## Modules

- new freecad/profile_builder/beams.py
- new freecad/profile_builder/loads.py
- `feature.py`
- `panels.py`
- `taskpanel.py`
- `cutlist.py`
- `commands.py`
- `simple_panel.py`
- `tests/test_beams.py`
- `tests/freecad_smoke.py`
