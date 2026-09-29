# Frame stiffness and natural-frequency model with joint-stiffness bounds and variant comparison

| | |
|---|---|
| Status | Partly done |
| Category | Analysis |
| Effort | XL (first estimate L) |
| Value | low |
| Proposed from | engineering |

## Status

First stage done (branch `feature/frame-stiffness`): a **Frame stiffness...** command that analyses the
frame at two joint-stiffness bounds and compares it with a stored baseline.

Done:
- `frame_model.py`: a pure numpy/scipy 3D direct-stiffness solver. It has 12-DOF beams with consistent mass,
  rigid end offsets, rotational springs at beam ends, static solves with strain energy per beam and spring,
  modal analysis, mass participation to name the modes (sways in X/Y, twists, bounces vertically, local),
  and a mechanism check that names the nodes that move. `tests/test_frame_model.py` checks it against
  closed forms: cantilevers, portal frames (fixed, pinned, semi-rigid), frequencies, a tip mass, a twist
  mode and mechanisms.
- `frame_stiffness.py` (no GUI) builds the model from the document:
  - Profiles on path edges are beams with E·Ix/Iy from the modelled section.
  - Nodes are the joints and the free ends. Passing members are split at their T-junctions.
  - Anchor offsets (`Frame.center_offset`) and the trimmed part of a butting end are rigid links.
  - At each joint the through profile (or the first profile of a miter) is rigid. Every other end hangs
    on a rotational spring k = factor · E·I/L of that profile. The loose bound defaults to 0.5, the
    EN 1993-1-8 limit for a nominally pinned joint; AISC 360 uses 2 for "simple". The stiff bound
    defaults to rigid.
  - Mass comes from the pieces (overhangs are lumped at the nodes), from panels (lumped at their corner
    nodes) and from an optional mass on top.
  - Supports are the lowest nodes, pinned or fixed. Parts that do not reach them are left out and listed.
  - Profiles with errors, profiles off sketch edges and panels with errors are listed as left out, and
    the report is marked incomplete.
- Outputs, for both bounds:
  - sideways stiffness at the top in X and Y (unit force shared over the highest nodes);
  - twist stiffness about the vertical axis through their centre;
  - the first three natural frequencies, with the mode shape;
  - where the frame flexes: the share of strain energy in the joints, and the largest members or joints.
- A "Frame stiffness" document object holds the settings (loose and stiff joint factors, supports,
  mass on top) and the baseline as JSON. The report shows ratios against the baseline
  ("1.1–1.9×"), the mass change and, when prices are set, the cost change in the document's currency.
- The task panel (`frame_ui.py`) shows the results live as the settings change, with Set/Clear baseline
  and Print report. It says at the top that the numbers are estimates with joint-stiffness bounds. OK
  keeps the settings and baseline; Cancel undoes them. The report is also printed to the report view.
- Values go through FreeCAD's unit schema: kN/m or lbf/in, N·m/° or lbf·ft/°, kg or lb. When a schema has
  no rule for a quantity, it falls back to metric or imperial by the schema. The mass on top accepts
  "11 lb" or "5 kg".
- numpy and scipy are loaded only when the analysis runs, so the workbench still loads without them.
- `tests/freecad_stiffness.py` covers:
  - a 2040 portal against the closed form with rigid end zones and joint springs (within 0.2 %), and a
    400 mm 2020 cube against the two-face closed form at both bounds;
  - mechanisms, X/Y symmetry and sway/twist mode names;
  - fixed feet, mass on top, the baseline and its ratios, save and reload;
  - left-out objects, panel mass, T-junction splitting and free ends;
  - the task panel run headless, and the unit schemas (Standard, Imperial decimal, MKS).
- A 184-profile frame (4 × 3 × 3 bays of 4040) analyses in about 1 s.

Not done yet:
- On-face panels as equivalent shear diagonals. Panels add mass only, so a panelled enclosure comes out
  far too soft. The report says so.
- Strain-energy colouring of members and joints in the 3D view. The shares are shown only as text.
- Payload mass points at chosen nodes, and other load cases (a point load, deflection under a machine).
- A per-joint stiffness from the connection method (see
  [joint-connection-machining](joint-connection-machining.md)). Today one factor applies to all joints.
- A torsion constant from the section itself. J is taken as 15 % of the polar moment, a rough value for
  slotted sections.
- Diagonal braces: the model handles any angle, but butt joints need perpendicular profiles until
  [angled butt joints](angled-butt-joints.md) exist.
- Free profiles (no path edge) are not in the model.
- The solver is dense, which is fine up to a few thousand DOFs, or a few hundred profiles.
- The GUI has not been run in FreeCAD itself yet. The panel was built and driven headless in freecadcmd
  and rendered off screen.

## Problem

Beyond braced or unbraced, users want to compare designs: whether 2040 posts or an extra mid-rail make the frame stiffer, and by how much. For 3D printers and CNC machines, the first frame mode matters for ringing and chatter; for machine stands and workstations, deflection under load matters more. Absolute numbers are unreliable, because joint stiffness is unknown.

## Proposal

A 3D direct-stiffness beam model assembled from the document:
- Members are the profiles on path edges, with E·Ix/Iy/J from the section-property features.
- Nodes come from the joints. Passing members are split at T-junctions, and anchor offsets are rigid links (Frame.center_offset).
- On-face panels become equivalent shear diagonals. Mass comes from profiles, panels and payload mass points.
- Each butt joint is a rotational spring, solved twice (near-pinned and rigid), so every result is a range.

Outputs: lateral stiffness at the top in X and Y, twist (N/mm), the first 3 natural frequencies, and each member's and joint's share of strain energy, shown by colouring ('this joint takes 40% of the racking').

The key presentation choice: store a baseline in the document and report relative changes ('2.1-2.6x stiffer than baseline, +0.8 kg, +14.00' in the document's currency), which hold up even when absolute values don't. Absolute values go through FreeCAD's unit schema (FreeCAD.Units) rather than fixed N/mm and kg, so users on an imperial schema are not left converting. numpy 1.26 and scipy 1.16 ship with FreeCAD 1.1 (checked). The solver module stays free of FreeCAD imports and is tested against portal-frame and cantilever closed forms.

## What exists today

Confirmed: numpy 1.26.4 and scipy 1.16.3 ship with FreeCAD 1.1.3. The first stage (see Status) builds on
them. FreeCAD's unit schemas turn out to have rules for stiffness in only some schemas (Standard, MKS,
US customary, Imperial decimal) and for moments only in Standard. Frequencies show as "1/s" outside
Standard and MKS. The report therefore falls back to its own metric or imperial units where a schema has
no rule, and always shows frequencies in Hz.

## Implementation approach

1. frame_model.py (pure numpy):
   - 12-DOF 3D beam elements, with rigid offset links from Frame.center_offset for anchored members.
   - A rotational spring per butt joint, solved at two stiffness bounds.
   - Static solve, plus modal analysis with scipy.linalg.eigh(K, M).
2. Graph builder (FreeCAD level):
   - Nodes from joint.Shape vertices.
   - Elements from profiles, split where they appear in PassingMembers.
   - Mass from Profile.Mass and Panel.Mass, plus lumped payload points.
   - On-face panels as equivalent diagonals.
3. Store the baseline as JSON on a document object and report ratios in a cutlist block before building any colouring UI.
4. Test against cantilever and portal-frame closed forms with uvx pytest --with numpy --with scipy.

## Blockers and caveats

- Unknown joint stiffness dominates the result. An unbraced cube at the near-pinned bound is a mechanism, and even the design-to-design ratios depend on the assumed joint stiffness.
- T-nut slip is nonlinear.
- The equivalent stiffness of a screwed acrylic panel is highly uncertain.
- The input and results UI is large.
- Most useful to CNC and machine builders comparing variants. For enclosures and simple printer frames, the racking audit answers the main question. At best a follow-up to member-load-check.

## Risks

- Without bracing, a near-pinned cube is a mechanism, so the lower bound needs a minimum joint stiffness and a clear 'depends entirely on the joints' message.
- T-nut joints slip, which a linear model ignores.
- Machine resonances are often dominated by belts, drives, the toolhead or spindle, so present frequencies as frame-only.
- pytest via uvx needs --with numpy --with scipy.
- The UI for loads and results is a lot of work, so the effort is easy to underestimate. Build the racking audit first.

## Prior art

FreeCAD FEM can do beam analysis (CalculiX), but its 1D sections are only rectangle, circle, pipe and ellipse, and setting it up by hand for a frame that is still changing is heavy. No T-slot addon links the modelled frame to an analysis.

## Modules

As built in the first stage:
- new `frame_model.py`: the solver (pure numpy/scipy)
- new `frame_stiffness.py`: the builder, the analysis, the settings object, the baseline and the unit
  formatting (no GUI)
- new `frame_ui.py`: the command and the task panel
- `commands.py`, `init_gui.py`: one registration line and one toolbar entry each
- new `tests/test_frame_model.py`, `tests/freecad_stiffness.py`

The results stay out of the cut list. `joints.py`, `feature.py`, `panels.py` and `cutlist.py` are read
but not changed. Later stages would touch `panels.py` for the shear diagonals and the view providers for
the colouring.
