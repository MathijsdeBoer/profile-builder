# Angled butt joints for diagonal braces

| | |
|---|---|
| Status | Planned |
| Category | Joints & assembly |
| Effort | M (first estimate M) |
| Value | medium |
| Proposed from | competitors |

## Problem

adjustment() raises 'butt joints need perpendicular profiles ... use a miter joint' for any member that is not square to the through profile. Diagonal braces in machine stands and workstations, knee braces under shelves and worktops, A-frame legs, gantry braces and spool-holder arms butt against another profile's face at 30-60°. Today they can only be built by hand, as free profiles with manual miters, and they don't follow the sketch. The racking audit would recommend diagonals that the joint system can't make.

## Proposal

When a member meets the through member at an angle, trim it so its end lies on the through member's face plane:
- Pick the through-frame face whose normal opposes the brace direction.
- Cut the brace with a miter of (90° minus the meeting angle), across the brace section axis that matches the projected face normal, using the same 'square to the section' check the miter code already does.
- Compute the length offset at the section centre. The saw angle appears in the existing miter columns of the cut list.
It also works when a brace ends mid-profile (T-junction), and warns when the brace section overhangs the face.

## What exists today

Explicitly refused today. In joints.adjustment, PERPENDICULAR (0.02) < cos < PARALLEL raises 'butt joints need perpendicular profiles'. The error is raised inside the brace's execute, so the brace also drops silently out of the cut list (see frame-check). The miter code already has the 'square to the section' check (gx/gy > PARALLEL) and the centre-offset length correction to reuse.

## Implementation approach

joints.adjustment, angled branch for a butt member whose through member is known:
1. Take n = the component of -away perpendicular to through_frame.z, normalised. This is the face normal pointing towards the brace. The face plane lies at distance d = through_frame.support(n) + gap from the through axis.
2. Brace angle φ = acos(|away·through_frame.z|). Miter angle = 90° - φ.
3. Miter axis: project n into the brace section and require |g·frame.x| or |g·frame.y| > PARALLEL, as the miter branch does, else 'check Spin'. For braces in vertical or horizontal planes, _edge_placement makes this hold: local Y lies in a vertical plane, local X in a horizontal one.
4. Offset at the section centre: -(d - frame.center_offset().dot(n)) / (away·n), with the sign handled as in the miter branch.

through_member: exclude members that are neither parallel nor perpendicular to the majority from the automatic candidates, unless they are Manual or JointRole 'Runs through'. Otherwise the 'Longest' rule can pick the diagonal and every rail fails. Leave the passing → Manual → JointRole → rule order and the direction tie-break unchanged for orthogonal members.

Refuse a brace that ends in a corner joint together with other butting members. It would clash with the rail as well as the post and needs a two-plane cut, so the message is 'end the brace on the rail (T-junction)'. T-junction braces already come out of create_joints as passing-member joints.

Add MiterAcross to cutlist.collect's key, because for 2040 braces the axis changes the piece.

Smoke tests: a 45° and a 30° brace between a rail and a post in the cube. Check the saw length against the analytic value and that common() volume with the rail and post is below 1e-3.

## Blockers and caveats

Compound angles (a brace not in a plane containing the face normal) need a second rotation. Refuse those at first. The through-member filter touches the rule order that fixed the pinwheel bug, so the existing square, cube and swap smoke tests must keep passing unchanged. With the corner refusal it stays M. Trimming against several members at a corner would be L.

## Risks

- A compound angle (brace not in a plane containing a face normal) needs a second rotation. Start by refusing it with a clear 'check Spin' message.
- The perpendicular path, the through-member order (passing member, Manual, JointRole, rule) and the direction-based tie-breaking that fixed the pinwheel bug must stay unchanged.

## Prior art

FrameForge TrimmedProfile 'End Trim' with Simple fit (plane cut) and Perfect fit (coping) against arbitrary bodies, plus its End Miter tool. Misumi FRAMES supports braced frames with angle brackets.

## Modules

- `joints.py (adjustment, create_joints)`
- `tests/freecad_smoke.py`
