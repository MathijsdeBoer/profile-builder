# Reference integrity: renames, deleted joints and deleted edges

| | |
|---|---|
| Status | Done |
| Category | FreeCAD integration & UX |
| Effort | M (first estimate M) |
| Value | high |
| Proposed from | freecad-ux |

## Status

Joints keep a hand-picked profile by object name (ThroughName), removing a joint resets the miters it set, and a profile whose sketch line was deleted gives a clear message.

## Problem

Scratch scripts in FreeCAD 1.1 show three silent failures:
1. Swap joint stores the chosen through profile by Label (joint.Through, matched with obj.Label == joint.Through). After the profiles are renamed, through_member() no longer matches and falls back to the rule, so a hand-picked corner flips on the next recompute.
2. Deleting a miter joint leaves the profile at MiterStart -45 with a mitered saw length, although nothing is joined any more.
3. After a sketch line is deleted, 1.1's toponaming remaps the other profiles correctly, but the orphaned profile fails with a cryptic "'Part.Shape' object has no attribute 'Curve'" on PathEdge '?Edge1'. On FreeCAD 0.21, which package.xml still claims to support, there is no toponaming, so the other profiles would silently jump to neighbouring edges.
PassingMembers also stores object names, and FreeCAD can reuse a deleted object's name.

## Proposal

Changes:
- Store the manual through member by object Name in a hidden property. Keep the Label enumeration for display only, and migrate old documents in onDocumentRestored.
- Record which miters a joint drove, and reset them when StartJoint or EndJoint is cleared (onChanged), so unjoining restores a square cut.
- Add onDelete on ViewProviderJoint and ViewProviderProfile to tidy up in the same undo transaction: remove the profile from PassingMembers, and delete joints left with fewer than two members.
- In execute, detect a missing or '?'-prefixed sub-element and raise 'Path edge Frame.Edge1 no longer exists; use Reattach'.
- Add 'Reattach' (select a profile and a new edge) and 'Unjoin' commands.
- For 0.21, either bump freecadmin to 1.0 or store the sketch geometry Tag as a fallback key.

## What exists today

All three failures reproduced in FreeCAD 1.1.3 with the current code:
1. Swap, then rename the profiles. When only a profile was recomputed, one side went back to 420 mm while its neighbour stayed at 400 mm, so the pieces overlap. When the joint was recomputed, Joint.execute refreshed the Through enumeration, which fell back to the first label ('Side A'), and the swap was lost for good.
2. removeObject on a miter joint left StartJoint=None but MiterStart=-45 and a 420 mm saw length.
3. After sketch.delGeometry(0), the other profiles were correctly remapped to Edge1-3. The orphaned profile got PathEdge '?Edge1' and failed with "'Part.Shape' object has no attribute 'Curve'".
The only existing guard is that passing_of() drops names that no longer resolve.

## Implementation approach

1. joints.py:
   - Add a hidden ThroughName (App::PropertyString, editor mode 2). swap() and onChanged('Through') resolve the label to an object Name among ends_of().
   - through_member() matches by Name, falling back to Label for old documents.
   - Joint.execute, when it refreshes the Through enumeration, re-selects the current label of the object named ThroughName, so it no longer falls back to index 0.
   - onDocumentRestored migrates Manual joints by matching Through against the current labels.
   - Joint.execute prunes PassingMembers names that no longer resolve to profiles, and reports a joint with fewer than 2 members as an error.
2. feature.py:
   - Add hidden MiterStartByJoint and MiterEndByJoint flags, set in execute whenever a joint drives the miter. If the joint link is gone and the flag is set, reset the miter to 0 and clear the flag in the same execute.
   - This works for macros and for Std_Delete alike. ViewProvider onDelete only runs for GUI deletes and runs around the confirmation dialog.
3. feature.path_edge(): if the sub-name starts with '?' or getSubObject returns no edge, raise ValueError('Path edge <Label>.EdgeN no longer exists; use Reattach').
4. commands.py:
   - Reattach: a profile plus an edge selection sets PathEdge, then runs create_joints for the profile's free ends.
   - Unjoin: clears StartJoint/EndJoint and removes joints left with fewer than 2 members, in one transaction.
   - Optionally, ViewProviderJoint.onDelete removes a deleted joint's references in the same transaction.
5. package.xml: raise freecadmin to 1.0. 0.21 has no toponaming, so a deleted sketch line silently shifts the other profiles. That is simpler than keeping Sketcher geometry Tags.
6. Smoke tests for the three reproductions. The existing square, cube and pinwheel checks must stay green.

## Blockers and caveats

None. Keep the through-member ordering rules unchanged: this only changes how the manual choice is stored.

## Risks

- Changing how Through is stored touches the through-member ordering rules that CLAUDE.md flags as easy to break (the pinwheel bug), so the square and cube tests must stay green.
- In some FreeCAD versions onDelete runs before the confirmation dialog, so the cleanup has to tolerate a cancelled delete.

## Prior art

FreeCAD 1.0+ toponaming (element-map shadow names in PropertyLinkSub) already covers edge renumbering in 1.1. Sketcher geometry Tags are the pre-1.0 option.

## Modules

- `joints.py`
- `feature.py`
- `commands.py`
- `tests/freecad_smoke.py`
- `package.xml`
