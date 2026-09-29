# Frame stiffness and natural-frequency model with joint-stiffness bounds and variant comparison

| | |
|---|---|
| Status | Planned |
| Category | Analysis |
| Effort | XL (first estimate L) |
| Value | low |
| Proposed from | engineering |

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

Confirmed: numpy 1.26.4 and scipy 1.16.3 ship with FreeCAD 1.1.3.

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

- new freecad/profile_builder/frame_model.py
- new freecad/profile_builder/frame_ui.py
- `joints.py`
- `feature.py`
- `panels.py`
- `cutlist.py`
- `commands.py`
- `tests/test_frame_model.py`
