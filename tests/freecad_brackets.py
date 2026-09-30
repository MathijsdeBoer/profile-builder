"""Headless test of bracket placement. Run with:  freecadcmd tests/freecad_brackets.py

A small L-shaped Part solid with slot keys stands in for a supplier's STEP
bracket. It is modelled in a skewed position, as imports are, so the
calibration has to find its frame. One section also writes it to a real STEP
file and imports that.

A traceback about "no bracket part" is expected: that is a deliberate error case.
"""

import os
import sys
import tempfile

import freecad

ROOT = os.getcwd()
# FreeCAD may already have loaded an installed copy of the workbench (for
# example through a link in its Mod folder) before this script runs. Drop it
# and put this checkout first, or a worktree would silently test other code.
for _name in [m for m in sys.modules if m == "freecad.profile_builder" or m.startswith("freecad.profile_builder.")]:
    del sys.modules[_name]
freecad.__path__.insert(0, os.path.join(ROOT, "freecad"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402

from freecad.profile_builder import brackets, cutlist, feature, joints  # noqa: E402

_loaded = os.path.normcase(os.path.realpath(feature.__file__))
if not _loaded.startswith(os.path.normcase(os.path.realpath(ROOT))):
    raise SystemExit(f"testing the wrong copy of the workbench: {_loaded} is not under {ROOT}")
print(f"testing {os.path.dirname(_loaded)}")

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


V = App.Vector

# ---- the test bracket ---------------------------------------------------------------
# In its own frame: contact faces at y = 0 (leg 1, 25 long along +X) and x = 0
# (leg 2, 15 long along +Y), 3 thick, 16 wide across Z, with a 5.6 mm wide key
# under each leg that fits the 6.2 mm opening of a 20 series slot.
LEG1, LEG2, THICK, WIDTH, KEY, KEY_DEPTH = 25.0, 15.0, 3.0, 16.0, 5.6, 1.5


def l_bracket():
    leg1 = Part.makeBox(LEG1, THICK, WIDTH, V(0, 0, -WIDTH / 2))
    leg2 = Part.makeBox(THICK, LEG2, WIDTH, V(0, 0, -WIDTH / 2))
    key1 = Part.makeBox(LEG1 - 3, KEY_DEPTH, KEY, V(3, -KEY_DEPTH, -KEY / 2))
    key2 = Part.makeBox(KEY_DEPTH, LEG2 - 3, KEY, V(-KEY_DEPTH, 3, -KEY / 2))
    return leg1.fuse([leg2, key1, key2]).removeSplitter()


def faces_where(shape, frame, test):
    """Indices (1-based) of the faces whose bounding box in the bracket frame passes ``test``."""
    back = frame.inverse().toMatrix()
    return [i for i, face in enumerate(shape.Faces, start=1) if test(face.transformed(back).BoundBox)]


def vertex_at(shape, frame, point):
    for i, v in enumerate(shape.Vertexes, start=1):
        if (frame.inverse().multVec(v.Point) - point).Length < 1e-6:
            return i
    return None


def canonical_faces(shape, frame):
    """Indices of the leg-1 and leg-2 contact faces and a corner vertex of a bracket modelled at ``frame``."""
    leg1 = faces_where(shape, frame, lambda bb: abs(bb.YMin) < 1e-6 and abs(bb.YMax) < 1e-6 and bb.XMax > LEG1 - 1e-6)
    leg2 = faces_where(shape, frame, lambda bb: abs(bb.XMin) < 1e-6 and abs(bb.XMax) < 1e-6 and bb.YMax > LEG2 - 1e-6)
    return (leg1[0] if len(leg1) == 1 else None, leg2[0] if len(leg2) == 1 else None,
            vertex_at(shape, frame, V(0, 0, -WIDTH / 2)))


def same_placement(a, b, tol=1e-6):
    return (a.Base - b.Base).Length < tol and all(
        (a.Rotation.multVec(u) - b.Rotation.multVec(u)).Length < tol for u in (V(1, 0, 0), V(0, 1, 0)))


doc = App.newDocument("brackets")
L = l_bracket()
check(L.isValid() and len(L.Solids) == 1, "test bracket builds")

# ---- calibration -----------------------------------------------------------------------

# A plain Part feature whose geometry is skewed, like an import with its own origin.
skew = App.Placement(V(30, -50, 12), App.Rotation(V(1, 2, 3), 40))
raw = doc.addObject("Part::Feature", "RawBracket")
raw.Shape = L.transformed(skew.toMatrix(), True)  # geometry, not a location
raw.Placement = App.Placement(V(500, 500, 0), App.Rotation(V(0, 0, 1), 15))  # ignored by links
doc.recompute()
f1, f2, v0 = canonical_faces(raw.Shape, raw.Placement.multiply(skew))
check(None not in (f1, f2, v0), f"contact faces found ({f1}, {f2}, {v0})")
part, frame, notes = brackets.calibrate([(raw, f"Face{f1}"), (raw, f"Face{f2}"), (raw, f"Vertex{v0}")])
check(part == raw and same_placement(frame, skew), f"calibration recovers the bracket frame ({frame} vs {skew})")
check(not notes, f"the corner vertex, at one end of the width, is accepted ({notes})")
world = raw.Placement.multiply(skew)
tip = vertex_at(raw.Shape, world, V(LEG1, 0, -WIDTH / 2))
_part, _frame, notes = brackets.calibrate([(raw, f"Face{f1}"), (raw, f"Face{f2}"), (raw, f"Vertex{tip}")])
check(any("vertex" in n for n in notes), f"a vertex away from the corner is noted ({notes})")

try:
    brackets.calibrate([(raw, f"Face{f1}")])
    check(False, "one face is not enough")
except ValueError as e:
    check("two contact faces" in str(e), f"one face is refused ({e})")

inner = faces_where(raw.Shape, world, lambda bb: abs(bb.YMin - THICK) < 1e-6 and abs(bb.YMax - THICK) < 1e-6
                    and bb.XMax > LEG1 - 1e-6)
inner += faces_where(raw.Shape, world, lambda bb: abs(bb.XMin - THICK) < 1e-6 and abs(bb.XMax - THICK) < 1e-6
                     and bb.YMax > LEG2 - 1e-6)
try:
    brackets.calibrate([(raw, f"Face{inner[0]}"), (raw, f"Face{inner[1]}")])
    check(False, "inner faces of the L are refused")
except ValueError as e:
    check("inside of the bracket" in str(e), f"inner faces of the L are refused ({e})")

top = faces_where(raw.Shape, world, lambda bb: abs(bb.ZMin - WIDTH / 2) < 1e-6)
try:
    brackets.calibrate([(raw, f"Face{f1}"), (raw, f"Face{top[0]}"), (raw, f"Face{f2}")])
    check(False, "three faces are refused")
except ValueError as e:
    check("two contact faces" in str(e), f"three faces are refused ({e})")

# A STEP import usually is an App::Part holding a body, both with placements.
asm = doc.addObject("App::Part", "StepBracket")
body = doc.addObject("Part::Feature", "StepBody")
inside = App.Placement(V(-7, 3, 40), App.Rotation(V(0, 1, 0), 90))
body.Shape = L.transformed(skew.toMatrix(), True)  # geometry, not a location
asm.addObject(body)
body.Placement = inside
asm.Placement = App.Placement(V(0, -800, 300), App.Rotation(V(1, 0, 0), 25))
doc.recompute()
s1, s2, _v = canonical_faces(body.Shape, inside.multiply(skew))  # a body's Shape is in its container
part, step_frame, _notes = brackets.calibrate([(asm, f"StepBody.Face{s1}"), (asm, f"StepBody.Face{s2}")])
check(part == asm and same_placement(step_frame, inside.multiply(skew)),
      "calibration through an App::Part (as STEP imports are)")
group = doc.addObject("App::DocumentObjectGroup", "Imports")
group.addObject(asm)
part, grouped, _notes = brackets.calibrate([(group, f"StepBracket.StepBody.Face{s1}"),
                                            (group, f"StepBracket.StepBody.Face{s2}")])
check(part == asm and same_placement(grouped, step_frame), "picks through a plain group link the part, not the group")

# ---- the 400 mm cube of 2020 from the smoke test ------------------------------------------


def lines_object(name, segments):
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = Part.makeCompound([Part.makeLine(V(*a), V(*b)) for a, b in segments])
    return obj


S = 400
corners = [(0, 0), (S, 0), (S, S), (0, S)]
segments = []
for z in (0, S):
    segments += [((*a, z), (*b, z)) for a, b in zip(corners, corners[1:] + corners[:1])]
segments += [((*c, 0), (*c, S)) for c in corners]


def build_cube():
    """(lines, profiles, joints) of the 400 mm cube of 2020 in ``doc``, posts running through."""
    lines = lines_object("CubeLines", segments)
    doc.recompute()
    cube = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(lines, f"Edge{i + 1}")) for i in range(12)]
    doc.recompute()
    cube_joints = joints.create_joints(doc, cube, "Butt", "Vertical")
    doc.recompute()
    return lines, cube, cube_joints


lines, cube, cube_joints = build_cube()
check(len(cube_joints) == 8, "cube: 8 joints")

objects_before = len(doc.Objects)
br = brackets.make_brackets(doc, asm, cube_joints, step_frame, ArticleNumber="BR-2020-L")
doc.recompute()
check(br.isValid() and br.Count == 24 and br.ElementCount == 24, f"cube: 24 inner brackets ({br.Count})")
check(len(doc.Objects) == objects_before + 1 and not any(o.TypeId == "App::LinkElement" for o in doc.Objects),
      "cube: no objects created for the elements")
check(sorted(m.Name for m in br.Members) == sorted(p.Name for p in cube), "cube: Members lists the 12 profiles")
check(not any(br in p.OutList or br in j.OutList for p in cube for j in cube_joints),
      "no profile or joint links to the brackets")

LOCAL = Part.getShape(asm, "", transform=False)


def placed():
    return [LOCAL.transformed(br.Placement.multiply(pl).toMatrix()) for pl in br.PlacementList[:br.Count]]


def fit_report(profiles):
    """(pieces not touching exactly their two profiles, overlap with profiles, overlap between brackets)."""
    shapes = placed()
    by_label = {p.Label: p for p in profiles}
    wrong, overlap, clash = [], 0.0, 0.0
    for i, (shape, where) in enumerate(zip(shapes, br.Positions)):
        pair = {s.strip() for s in where.split(":", 1)[1].split("/")}
        touching = set()
        for p in profiles:
            if not shape.BoundBox.intersect(p.Shape.BoundBox):
                continue
            if shape.distToShape(p.Shape)[0] < 1e-6:
                touching.add(p.Label)
            overlap += shape.common(p.Shape).Volume
        if touching != pair or not pair <= set(by_label):
            wrong.append((i, where, sorted(touching)))
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            if shapes[i].BoundBox.intersect(shapes[j].BoundBox):
                clash += shapes[i].common(shapes[j]).Volume
    return wrong, overlap, clash


wrong, overlap, clash = fit_report(cube)
check(not wrong, f"cube: each bracket touches exactly its two profiles ({wrong[:3]})")
check(overlap < 1e-3, f"cube: brackets and keys do not overlap the profiles ({overlap:.4f} mm3)")
check(clash < 1e-3, f"cube: brackets do not overlap each other ({clash:.4f} mm3)")
shape = Part.getShape(br)
check(len(shape.Solids) == 24 and abs(shape.Volume - 24 * L.Volume) < 1e-6,
      f"cube: the link array shows 24 brackets ({len(shape.Solids)})")
# At the bottom corner in the origin: two brackets on the rails against the post, one between the rails.
origin_corner = sorted((round(pl.Base.x, 3), round(pl.Base.y, 3), round(pl.Base.z, 3))
                       for pl in (br.Placement.multiply(p).multiply(step_frame) for p in br.PlacementList)
                       if pl.Base.Length < 20)
check(origin_corner == [(0.0, 10.0, 10.0), (10.0, 0.0, 10.0), (10.0, 10.0, 0.0)],
      f"cube: bracket corners at the origin joint ({origin_corner})")

br.Rule = "All open faces"
doc.recompute()
check(br.Count == 24, f"cube: no T-junctions, so all open faces is also 24 ({br.Count})")
br.Rule = "Inner faces"

# The cut list gets a Hardware block.
cutlist.recompute_if_needed(doc)
report = cutlist.build_report(doc)
check(report.hardware == [(24, "StepBracket", "BR-2020-L", br.Label)], f"hardware row ({report.hardware})")
br.Item = "Inner corner bracket 20"
check(brackets.problem(br) is not None, "an edited Brackets object is not counted before a recompute")
cutlist.recompute_if_needed(doc)
report = cutlist.build_report(doc)
check(report.hardware[0][1] == "Inner corner bracket 20", "hardware item name can be typed")
blocks = cutlist._blocks(report)
hw = [b for b in blocks if b[0].startswith("Hardware")]
check(len(hw) == 1 and hw[0][1] == cutlist.HARDWARE_HEADER, f"hardware block in the lists ({[b[0] for b in blocks]})")
csv_path = os.path.join(tempfile.gettempdir(), "pb_brackets.csv")
cutlist.write_csv(report, csv_path, delimiter=";", decimal=",")
text = open(csv_path, encoding="utf-8-sig").read()
check("Inner corner bracket 20;BR-2020-L" in text, "hardware row in the CSV")
sheet = cutlist.write_spreadsheet(doc, report)
check(sheet.isValid(), "hardware block in the spreadsheet")

# Swapping a joint moves the brackets with it.
corner = cube[0].StartJoint
joints.swap(corner)
doc.recompute()
wrong, overlap, clash = fit_report(cube)
check(br.Count == 24 and not wrong and overlap < 1e-3 and clash < 1e-3,
      f"swapped joint: still 24 brackets, touching and not overlapping ({br.Count}, {wrong[:2]}, {overlap:.4f})")
through, _e = joints.through_member(corner)
check(any(where.startswith(corner.Label) and through.Label in where for where in br.Positions),
      "swapped joint: brackets name the new through profile")

# Unequal legs can change sides.
before = [shape.BoundBox for shape in placed()]
br.SwapLegs = True
doc.recompute()
after = [shape.BoundBox for shape in placed()]
wrong, overlap, clash = fit_report(cube)
check(br.Count == 24 and any(abs(a.XLength - b.XLength) > 1 for a, b in zip(before, after)),
      "swap legs turns the brackets")
check(not wrong and overlap < 1e-3 and clash < 1e-3,
      f"swap legs: still touching, no overlap ({wrong[:2]}, {overlap:.4f})")
br.SwapLegs = False

# A slot offset moves the keys out of the slots, so they hit the lips.
br.SlotOffset = 2.0
doc.recompute()
_wrong, overlap, _clash = fit_report(cube)
check(overlap > 1.0, f"slot offset shifts the brackets across the slot ({overlap:.2f} mm3 into the lips)")
br.SlotOffset = 0.0
doc.recompute()

# A joint gap: the profiles stop short of each other, and the brackets bridge it.
corner.Gap = 1.0
doc.recompute()
wrong, overlap, clash = fit_report(cube)
check(br.Count == 24 and not wrong and overlap < 1e-3 and clash < 1e-3,
      f"joint gap: brackets still in all three corners ({br.Count}, {wrong[:2]}, {overlap:.4f})")
corner.Gap = 0.0

# Bigger posts: the brackets follow, and the rails no longer close a corner between them.
corner.ThroughRule = "Vertical"  # undo the swap: posts run through everywhere again
for p in cube[8:]:
    p.Series = "30-8"
doc.recompute()
wrong, overlap, clash = fit_report(cube)
check(br.Count == 16, f"3030 posts: 16 brackets, none between the rails ({br.Count})")
check(not wrong and overlap < 1e-3 and clash < 1e-3, f"3030 posts: touching, no overlap ({wrong[:2]}, {overlap:.4f})")

# Stretching the sketch lines: the brackets follow.
stretched = [((a[0] * 1.5, a[1], a[2]), (b[0] * 1.5, b[1], b[2])) for a, b in segments]
lines.Shape = Part.makeCompound([Part.makeLine(V(*a), V(*b)) for a, b in stretched])
doc.recompute()
wrong, overlap, clash = fit_report(cube)
check(br.Count == 16 and not wrong and overlap < 1e-3, f"stretched cube: brackets follow ({wrong[:2]})")

# Picking the faces on a placed bracket calibrates as well as on the part.
index = 5
shape = placed()[index]
local_frame = br.Placement.multiply(br.PlacementList[index]).multiply(step_frame)
e1, e2, _v = canonical_faces(shape, local_frame)
face_names = [f"{index}.StepBody.Face{e1}", f"{index}.StepBody.Face{e2}"]
try:
    part, again, _notes = brackets.calibrate([(br, face_names[0]), (br, face_names[1])])
    check(part == asm and same_placement(again, step_frame), "calibration from picks on a placed bracket")
except Exception as e:  # noqa: BLE001
    check(False, f"calibration from picks on a placed bracket raised {e!r}")

# Save and reopen.
path = os.path.join(tempfile.gettempdir(), "pb_brackets.FCStd")
saved = [App.Placement(p) for p in br.PlacementList]
doc.saveAs(path)
App.closeDocument(doc.Name)
doc = App.openDocument(path)
br = [o for o in doc.Objects if brackets.is_brackets(o)][0]
check(br.Count == 16 and len(br.Members) == 12 and br.ArticleNumber == "BR-2020-L", "reopened: brackets kept")
for o in doc.Objects:
    o.touch()
doc.recompute()
check(br.isValid() and all(same_placement(a, b) for a, b in zip(saved, br.PlacementList)),
      "reopened: same placements after a recompute")
asm = doc.getObject("StepBracket")
cube = [o for o in doc.Objects if feature.is_profile(o)]
LOCAL = Part.getShape(asm, "", transform=False)
wrong, overlap, _clash = fit_report(cube)
check(not wrong and overlap < 1e-3, "reopened: brackets still fit")

# Undo of the creation removes it cleanly.
doc.UndoMode = 1
doc.openTransaction("more brackets")
extra = brackets.make_brackets(doc, asm, [cube[0].StartJoint], step_frame)
doc.recompute()
doc.commitTransaction()
check(extra.Count in (2, 3), f"brackets at one joint ({extra.Count})")
name = extra.Name
doc.undo()
doc.recompute()
check(doc.getObject(name) is None and all(o.isValid() for o in doc.Objects), "undo removes the brackets")

# A missing part is an error, and the cut list says so.
doc.removeObject(asm.Name)
doc.removeObject("StepBody")
doc.recompute()
cutlist.recompute_if_needed(doc)
report = cutlist.build_report(doc)
check(not br.isValid() and any(br.Label in e and "no bracket part" in e for e in report.errors) and not report.hardware,
      f"no part: listed as an error, not counted ({report.errors})")
App.closeDocument(doc.Name)

# ---- rules at T-junctions: a goalpost whose posts stick out above the top rail ---------------

doc = App.newDocument("goalpost")
lines = lines_object("Goalpost", [((0, 0, 0), (0, 0, 500)), ((400, 0, 0), (400, 0, 500)),
                                  ((0, 0, 400), (400, 0, 400))])
doc.recompute()
goal = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(lines, f"Edge{i + 1}")) for i in range(3)]
doc.recompute()
goal_joints = joints.create_joints(doc, goal, "Butt", "Vertical")
doc.recompute()
part = doc.addObject("Part::Feature", "Bracket")
part.Shape = L
doc.recompute()
gb = brackets.make_brackets(doc, part, goal_joints)
doc.recompute()
LOCAL = L
br = gb
wrong, overlap, clash = fit_report(goal)
check(gb.Count == 2 and not wrong and overlap < 1e-3, f"goalpost: inner faces, 2 brackets under the rail ({gb.Count})")
check(all(pl.Base.z < 400 for pl in gb.PlacementList), "goalpost: under the rail, not on the posts' stubs")
gb.Rule = "All open faces"
doc.recompute()
wrong, overlap, clash = fit_report(goal)
check(gb.Count == 4 and not wrong and overlap < 1e-3 and clash < 1e-3,
      f"goalpost: all open faces, above the rail too ({gb.Count})")

# A closed face gets no bracket.
goal[2].ClosedTop = True  # the rail's top face (+Z)
doc.recompute()
check(gb.Count == 2, f"closed face: no brackets on it ({gb.Count})")
goal[2].ClosedTop = False
doc.recompute()

# A rail turned by Spin has no face flat in the corners: none there, and a note says why.
goal[2].Spin = 30
doc.recompute()
check(gb.Count == 0 and gb.Notes and all(f"{goal[2].Label} is turned by its Spin (30°) and has no face square to"
                                         in n for n in gb.Notes), f"turned rail: noted, no brackets ({gb.Notes})")
goal[2].Spin = 90  # a quarter turn keeps the faces square
doc.recompute()
wrong, overlap, clash = fit_report(goal)
check(gb.Count == 4 and not wrong and overlap < 1e-3 and not gb.Notes,
      f"rail turned a quarter turn: brackets again ({gb.Count}, {gb.Notes})")
goal[2].Spin = 0
doc.recompute()

# A 2040 rail lying flat has two slots on top, neither in line with the 2020 post's slot: no
# brackets there, and a note says why.
goal[2].Columns = 2
doc.recompute()
check(gb.Count == 0 and any("do not line up" in n for n in gb.Notes),
      f"flat 2040 rail: slots do not line up ({gb.Notes})")
# Standing on edge, its top and bottom faces have one slot each, in line with the posts'.
goal[2].Columns, goal[2].Rows = 1, 2
doc.recompute()
wrong, overlap, clash = fit_report(goal)
heights = sorted({round(pl.Base.z, 3) for pl in gb.PlacementList})
check(gb.Count == 4 and not wrong and overlap < 1e-3 and heights == [380.0, 420.0],
      f"2040 rail on edge: brackets at its top and bottom faces ({gb.Count}, {heights})")

# With AllJoints, a joint made later gets brackets too: a middle post under the rail.
gb.AllJoints = True
doc.recompute()
middle_line = lines_object("Middle", [((200, 0, 0), (200, 0, 400))])
doc.recompute()
middle = feature.make_profile("20-6", 1, 1, 100, doc, edge=(middle_line, "Edge1"))
doc.recompute()
new_joints = joints.create_joints(doc, goal + [middle], "Butt", "Vertical")
doc.recompute()
wrong, overlap, clash = fit_report(goal + [middle])
check(len(new_joints) == 1 and new_joints[0] in gb.Joints and gb.Count == 6 and middle in gb.Members,
      f"all joints: the new T-junction gets a bracket on each side ({gb.Count})")
check(not wrong and overlap < 1e-3 and clash < 1e-3, f"all joints: the new brackets fit ({wrong[:2]}, {overlap:.4f})")

# A rail trimmed short of a post leaves no corner there.
goal[2].ExtendStart = -5.0
doc.recompute()
check(gb.Count == 4, f"trimmed rail end: no brackets at that post ({gb.Count})")
goal[2].ExtendStart = 0.0
doc.recompute()

# The anchor moves the rail's section off its sketch line; the brackets follow its faces.
goal[2].Anchor = "Bottom center"
doc.recompute()
wrong, overlap, clash = fit_report(goal + [middle])
heights = sorted({round(pl.Base.z, 3) for pl in gb.PlacementList})
check(gb.Count == 6 and not wrong and overlap < 1e-3 and clash < 1e-3 and heights == [400.0, 440.0],
      f"anchored rail: brackets at its faces ({gb.Count}, {heights}, {wrong[:2]})")

# ---- Inner faces: which sides of a T-junction face into the frame -----------------------------
# A side faces into the frame where the profile running through carries on to another joint, not
# where it ends freely (a stub). Where it ends freely both ways, the side where the rest of the
# frame reaches further counts. None of this may depend on where the middle of the frame is.


def frame_with(name, segs):
    """(profiles, joints, bracket part) of a 2020 frame on ``segs`` in a new document, posts running through."""
    global doc
    doc = App.newDocument(name)
    shape_lines = lines_object("Lines", segs)
    doc.recompute()
    profs = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(shape_lines, f"Edge{i + 1}"))
             for i in range(len(segs))]
    doc.recompute()
    made = joints.create_joints(doc, profs, "Butt", "Vertical")
    doc.recompute()
    bracket_part = doc.addObject("Part::Feature", "Bracket")
    bracket_part.Shape = L
    doc.recompute()
    return profs, made, bracket_part


def base(pl):
    return tuple(round(c, 3) for c in pl.Base)


# A closed frame with a shelf rail a third of the way up: every corner under and over the shelf is
# enclosed, although the shelf is below the middle of the frame.
shelf_frame, shelf_joints, part = frame_with("shelf", [
    ((0, 0, 0), (0, 0, 600)), ((400, 0, 0), (400, 0, 600)),
    ((0, 0, 0), (400, 0, 0)), ((0, 0, 600), (400, 0, 600)), ((0, 0, 200), (400, 0, 200))])
shelf = shelf_frame[4]
br = brackets.make_brackets(doc, part, shelf_joints)
doc.recompute()
LOCAL = L
wrong, overlap, clash = fit_report(shelf_frame)
under = [pl for where, pl in zip(br.Positions, br.PlacementList) if shelf.Label in where and pl.Base.z < 200]
check(br.Count == 8 and len(under) == 2, f"shelf frame: inner faces on both sides of the shelf ({br.Count}, "
      f"{len(under)} under it)")
check(not wrong and overlap < 1e-3 and clash < 1e-3, f"shelf frame: the brackets fit ({wrong[:2]}, {overlap:.4f})")
check(not br.Notes, f"shelf frame: no notes ({br.Notes})")
tees = [j for j in shelf_joints if list(j.PassingMembers)]
only = brackets.make_brackets(doc, part, tees)
doc.recompute()
check(len(tees) == 2 and only.Count == 4 and sorted(j.Name for j in only.FrameJoints) ==
      sorted(j.Name for j in shelf_joints if j not in tees),
      f"shelf joints alone: the same 4 brackets, judged on the whole frame ({only.Count})")
check(not any(only in o.OutList or br in o.OutList for o in shelf_frame + shelf_joints),
      "no profile or joint links to the brackets")

# Posts standing out above the top rail: the stubs get none, the rest of the frame is unchanged.
stub_frame, stub_joints, part = frame_with("stubs", [
    ((0, 0, 0), (0, 0, 700)), ((400, 0, 0), (400, 0, 700)),
    ((0, 0, 0), (400, 0, 0)), ((0, 0, 600), (400, 0, 600)), ((0, 0, 200), (400, 0, 200))])
br = brackets.make_brackets(doc, part, stub_joints)
doc.recompute()
wrong, overlap, clash = fit_report(stub_frame)
top = sorted(base(pl) for where, pl in zip(br.Positions, br.PlacementList) if stub_frame[3].Label in where)
check(br.Count == 8 and len(top) == 2 and all(z < 600 for _x, _y, z in top) and not wrong and overlap < 1e-3,
      f"posts standing out: none on the stubs, 8 in all ({br.Count}, top rail: {top})")
br.Rule = "All open faces"
doc.recompute()
check(br.Count == 10, f"posts standing out, all open faces: on the stubs too ({br.Count})")

# The goalpost with its middle post off-centre: the rail carries on both ways from the middle post.
goal, goal_joints, part = frame_with("offcentre", [
    ((0, 0, 0), (0, 0, 500)), ((400, 0, 0), (400, 0, 500)), ((0, 0, 400), (400, 0, 400)),
    ((100, 0, 0), (100, 0, 400))])
br = brackets.make_brackets(doc, part, goal_joints)
doc.recompute()
wrong, overlap, clash = fit_report(goal)
at_middle = sorted(base(pl) for where, pl in zip(br.Positions, br.PlacementList) if goal[3].Label in where)
check(br.Count == 4 and len(at_middle) == 2 and at_middle[0][0] < 100 < at_middle[1][0] and not wrong
      and overlap < 1e-3 and clash < 1e-3,
      f"off-centre middle post: a bracket on each side of it, under the rail at the posts ({br.Count}, {at_middle})")
check(all(pl.Base.z < 400 for pl in br.PlacementList), "off-centre middle post: none on the posts' stubs")

# A joint made later on a post's stub encloses the space above the rail. The brackets at the rail's
# ends (no AllJoints) follow, although no profile they are at has changed.
ends = [j for j in goal_joints if goal[0].Name in j.PassingMembers or goal[1].Name in j.PassingMembers]
sel = brackets.make_brackets(doc, part, ends)
doc.recompute()
check(sel.Count == 2 and all(pl.Base.z < 400 for pl in sel.PlacementList), f"rail ends: under the rail ({sel.Count})")
upper_line = lines_object("Upper", [((0, 0, 450), (400, 0, 450))])
doc.recompute()
upper = feature.make_profile("20-6", 1, 1, 100, doc, edge=(upper_line, "Edge1"))
doc.recompute()
later = joints.create_joints(doc, goal + [upper], "Butt", "Vertical")
doc.recompute()
check(len(later) == 2 and sel.Count == 2 and all(400 < pl.Base.z < 450 for pl in sel.PlacementList)
      and all(j in sel.FrameJoints for j in later) and upper in sel.Members and not sel.Proxy.mustExecute(sel),
      f"a joint made later on the stubs: the brackets move up, into the enclosed side "
      f"({sel.Count}, {[base(pl) for pl in sel.PlacementList]})")

# ---- one bracket per slot: 40 x 40 profiles of the 20 series have two slots on each face ----------

doc = App.newDocument("wide")
lines = lines_object("Goalpost", [((0, 0, 0), (0, 0, 500)), ((400, 0, 0), (400, 0, 500)),
                                  ((0, 0, 400), (400, 0, 400))])
doc.recompute()
wide = [feature.make_profile("20-6", 2, 2, 100, doc, edge=(lines, f"Edge{i + 1}")) for i in range(3)]
doc.recompute()
joints.create_joints(doc, wide, "Butt", "Vertical")
doc.recompute()
part = doc.addObject("Part::Feature", "Bracket")
part.Shape = L
br = brackets.make_brackets(doc, part, brackets.all_joints(doc))
doc.recompute()
LOCAL = L
wrong, overlap, clash = fit_report(wide)
across = sorted({round(pl.Base.y, 3) for pl in br.PlacementList})
check(br.Count == 4 and across == [-10.0, 10.0],
      f"two slots per face: two brackets side by side ({br.Count}, {across})")
check(not wrong and overlap < 1e-3 and clash < 1e-3, f"two slots per face: they fit ({wrong[:2]}, {overlap:.4f})")

# ---- a real STEP file, exported and imported again as a supplier's file would be ---------------------

import Import  # noqa: E402

vendor = App.newDocument("vendor")
vendor_part = vendor.addObject("App::Part", "VendorBracket")
vendor_body = vendor.addObject("Part::Feature", "Body")
vendor_body.Shape = L.transformed(skew.toMatrix(), True)  # modelled around the vendor's own origin
vendor_part.addObject(vendor_body)
vendor.recompute()
step_path = os.path.join(tempfile.gettempdir(), "pb_brackets.step")
Import.export([vendor_part], step_path)
App.closeDocument(vendor.Name)

doc = App.newDocument("stepfile")
lines, cube, cube_joints = build_cube()
Import.insert(step_path, doc.Name)
doc.recompute()
imported = [o for o in doc.Objects if o.TypeId == "App::Part"]
bodies = [o for o in imported[0].Group if o.isDerivedFrom("Part::Feature")] if len(imported) == 1 else []
check(len(bodies) == 1, f"STEP file: imported as an App::Part holding the body ({[o.Name for o in imported]})")
if len(bodies) == 1:
    asm, body = imported[0], bodies[0]
    s1, s2, _v = canonical_faces(body.Shape, skew)  # a body's Shape is in its container
    part, frame, notes = brackets.calibrate([(asm, f"{body.Name}.Face{s1}"), (asm, f"{body.Name}.Face{s2}")])
    check(part == asm and same_placement(frame, skew, 1e-4) and not notes,
          f"STEP file: calibrated through the imported App::Part ({frame}, {notes})")
    br = brackets.make_brackets(doc, asm, cube_joints, frame)
    doc.recompute()
    LOCAL = Part.getShape(asm, "", transform=False)
    wrong, overlap, clash = fit_report(cube)
    check(len(LOCAL.Solids) == 1 and br.Count == 24 and not wrong and overlap < 1e-3 and clash < 1e-3,
          f"STEP file: 24 brackets on the cube, touching and not overlapping ({br.Count}, {wrong[:2]}, {overlap:.4f})")

# ---- nested containers: the part is the bracket, not a library or a design around it ---------------

doc = App.newDocument("nested")
lines, cube, cube_joints = build_cube()


def step_like(name):
    """An App::Part holding one body, as a STEP import gives it."""
    container = doc.addObject("App::Part", name)
    solid = doc.addObject("Part::Feature", name + "Body")
    solid.Shape = L.transformed(skew.toMatrix(), True)
    container.addObject(solid)
    return container, solid


def calibrated_count(part, frame):
    """(brackets placed, solids shown) of a Brackets object for ``part`` on the cube."""
    made = brackets.make_brackets(doc, part, cube_joints, frame)
    doc.recompute()
    result = made.Count, len(Part.getShape(made).Solids)
    doc.removeObject(made.Name)
    return result


library = doc.addObject("App::Part", "BracketLibrary")
lib_step, lib_body = step_like("LibStep")
bare = doc.addObject("Part::Feature", "Bracket30")
bare.Shape = L.transformed(skew.toMatrix(), True)
bare.Placement = App.Placement(V(200, 0, 0), App.Rotation())
library.addObject(lib_step)
library.addObject(bare)
doc.recompute()
s1, s2, _v = canonical_faces(lib_body.Shape, skew)
part, frame, _notes = brackets.calibrate([(library, f"LibStep.LibStepBody.Face{s1}"),
                                          (library, f"LibStep.LibStepBody.Face{s2}")])
check(part == lib_step and same_placement(frame, skew), f"library of brackets: its bracket is the part ({part.Label})")
check(calibrated_count(part, frame) == (24, 24), "library of brackets: one bracket in each corner, not the library")
b1, b2, _v = canonical_faces(bare.Shape, bare.Placement.multiply(skew))
part, frame, _notes = brackets.calibrate([(library, f"Bracket30.Face{b1}"), (library, f"Bracket30.Face{b2}")])
check(part == bare and same_placement(frame, skew), f"library of brackets: a bare bracket in it is the part ({part.Label})")
# A PartDesign body (here on a base feature): the body is the part, not the feature picked in it.
pd_base = doc.addObject("Part::Feature", "PdBase")
pd_base.Shape = L.transformed(skew.toMatrix(), True)
pd_body = doc.addObject("PartDesign::Body", "PdBody")
pd_body.BaseFeature = pd_base
doc.recompute()
p1, p2, _v = canonical_faces(pd_body.Shape, skew)
part, frame, _notes = brackets.calibrate([(pd_body, f"{pd_body.Tip.Name}.Face{p1}"),
                                          (pd_body, f"{pd_body.Tip.Name}.Face{p2}")])
check(part == pd_body and same_placement(frame, skew), f"PartDesign body: the body is the part ({part.Label})")

# The whole design in an App::Part: the frame's lines and profiles and the imported bracket.
printer = doc.addObject("App::Part", "Printer")
printer.addObject(lines)
for p in cube:
    printer.addObject(p)
printer_step, printer_body = step_like("PrinterStep")
printer.addObject(printer_step)
doc.recompute()
s1, s2, _v = canonical_faces(printer_body.Shape, skew)
part, frame, _notes = brackets.calibrate([(printer, f"PrinterStep.PrinterStepBody.Face{s1}"),
                                          (printer, f"PrinterStep.PrinterStepBody.Face{s2}")])
check(part == printer_step and same_placement(frame, skew),
      f"design in an App::Part: the bracket is the part, centred on its own width ({part.Label}, {frame})")
check(calibrated_count(part, frame) == (24, 24), "design in an App::Part: one bracket in each corner, not the design")
try:
    brackets.calibrate([(printer, f"{cube[0].Name}.Face1"), (printer, f"{cube[0].Name}.Face3")])
    check(False, "faces of a profile are refused as the bracket")
except ValueError as e:
    check("is or holds a profile" in str(e), f"faces of a profile are refused as the bracket ({e})")
check(brackets.holds_frame(printer) and brackets.holds_frame(doc.getObject("Joints"))
      and not brackets.holds_frame(printer_step) and not brackets.holds_frame(library),
      "holds_frame: the design and the joints group hold the frame, the brackets and the library do not")

# ---- a frame turned about Z, not lined up with world X and Y --------------------------------------


def turned_cube(angle, spin, order=range(12)):
    """(document, Brackets object, profiles) of the 400 mm cube turned by ``angle`` about Z.

    The profiles are made in ``order``, which decides their names; the posts get ``spin``.
    """
    turned = App.newDocument("turned")
    rot = App.Rotation(V(0, 0, 1), angle)
    ring = [rot.multVec(V(x, y, 0)) for x, y in corners]
    segs = []
    for z in (0, S):
        segs += [(a + V(0, 0, z), b + V(0, 0, z)) for a, b in zip(ring, ring[1:] + ring[:1])]
    segs += [(c, c + V(0, 0, S)) for c in ring]
    shape_lines = turned.addObject("Part::Feature", "CubeLines")
    shape_lines.Shape = Part.makeCompound([Part.makeLine(a, b) for a, b in segs])
    turned.recompute()
    profs = [None] * 12
    for i in order:
        profs[i] = feature.make_profile("20-6", 1, 1, 100, turned, edge=(shape_lines, f"Edge{i + 1}"))
    for p in profs[8:]:
        p.Spin = spin
    turned.recompute()
    made = joints.create_joints(turned, profs, "Butt", "Vertical")
    turned.recompute()
    bracket_part = turned.addObject("Part::Feature", "Bracket")
    bracket_part.Shape = L
    placed_by = brackets.make_brackets(turned, bracket_part, made)
    turned.recompute()
    return turned, placed_by, profs


def layout(obj):
    """The brackets as sorted (corner, leg 1, leg 2) tuples."""
    axes = [(pl.Base, pl.Rotation.multVec(V(1, 0, 0)), pl.Rotation.multVec(V(0, 1, 0)))
            for pl in obj.PlacementList[:obj.Count]]
    return sorted(tuple(tuple(round(c, 3) + 0.0 for c in (v.x, v.y, v.z)) for v in a) for a in axes)


turned, br, turned_profiles = turned_cube(30, 0)
post = turned_profiles[8]
check(br.Count == 0 and any(n.startswith(f"{post.StartJoint.Label}: {post.Label} has no face square to") for n in br.Notes)
      and not any("turned by" in n for n in br.Notes),
      f"frame turned 30°, posts not spun: the note names the post, not its Spin ({br.Notes[:1]})")
App.closeDocument(turned.Name)
turned, br, turned_profiles = turned_cube(30, 30)
LOCAL = L
wrong, overlap, clash = fit_report(turned_profiles)
check(br.Count == 24 and not wrong and overlap < 1e-3 and clash < 1e-3 and not br.Notes,
      f"frame turned 30°, posts spun to match: 24 brackets that fit ({br.Count}, {wrong[:2]}, {br.Notes[:1]})")
App.closeDocument(turned.Name)

# Turned 45°, the two rails at a corner are at equal angles to X and Y. Which leg goes on which rail
# must not depend on the order the profiles were made in, and must be the same at every corner.
for angle in (45, 135):
    turned, br, _p = turned_cube(angle, angle)
    forward = layout(br)
    App.closeDocument(turned.Name)
    turned, br, _p = turned_cube(angle, angle, reversed(range(12)))
    backward = layout(br)
    App.closeDocument(turned.Name)
    between_rails = [(x, y) for _c, x, y in forward if abs(x[2]) < 1e-6 and abs(y[2]) < 1e-6]
    diagonal = V(1, 1, 0) * (1 / 2 ** 0.5)
    check(len(forward) == 24 and forward == backward,
          f"frame turned {angle}°: the same brackets whatever the order the profiles were made in")
    check(len(between_rails) == 8 and all(abs(V(*x).dot(diagonal)) > 0.999 for x, _y in between_rails),
          f"frame turned {angle}°: leg 1 on the rails along the same diagonal at every corner ({between_rails[:2]})")

# ---- miter corners get no brackets yet, and say so -----------------------------------------

doc = App.newDocument("mitred")
lines = lines_object("Ring", [((0, 0, 0), (300, 0, 0)), ((300, 0, 0), (300, 200, 0)),
                              ((300, 200, 0), (0, 200, 0)), ((0, 200, 0), (0, 0, 0))])
doc.recompute()
ring = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(lines, f"Edge{i + 1}")) for i in range(4)]
doc.recompute()
ring_joints = joints.create_joints(doc, ring, "Miter")
doc.recompute()
part = doc.addObject("Part::Feature", "Bracket")
part.Shape = L
mb = brackets.make_brackets(doc, part, ring_joints)
doc.recompute()
check(mb.isValid() and mb.Count == 0 and len(mb.Notes) == 4 and "miter" in mb.Notes[0],
      f"miter joints: noted ({mb.Notes})")
check(list(mb.VisibilityList) == [False] and Part.getShape(mb).isNull(), "no brackets: nothing stray is shown")
report = cutlist.build_report(doc)
check(not report.hardware and any("miter joint" in w for w in report.warnings), "miter joints: note in the cut list")
for j in ring_joints:
    j.Type = "Butt"
doc.recompute()
check(mb.Count == 4 and all(mb.VisibilityList) and len(Part.getShape(mb).Solids) == 4,
      f"butt joints again: 4 brackets, shown ({mb.Count}, {mb.VisibilityList})")

# ---- the commands, with a stand-in for the GUI selection ----------------------------------------
# freecadcmd has no FreeCADGui.Selection; the stand-in hands the commands what an unresolved
# selection would: the top-level object and the full subname of each pick.

import types  # noqa: E402

from freecad.profile_builder import brackets_ui  # noqa: E402


class Picked:
    def __init__(self, obj, subs=()):
        self.Object, self.SubElementNames = obj, tuple(subs)


selection = {"ex": [], "objects": []}
shown, messages = [], []
brackets_ui.Gui = types.SimpleNamespace(
    Selection=types.SimpleNamespace(getSelectionEx=lambda doc="", resolve=1: selection["ex"],
                                    getSelection=lambda: selection["objects"], clearSelection=lambda: None),
    Control=types.SimpleNamespace(activeDialog=lambda: False, showDialog=shown.append))
brackets_ui._message = lambda text, title="": messages.append(text)
brackets_ui.task_panel = lambda obj: obj


def select(ex=(), objects=()):
    selection["ex"], selection["objects"] = list(ex), list(objects)


App.setActiveDocument(doc.Name)
raw = doc.addObject("Part::Feature", "Imported")
raw.Shape = L.transformed(skew.toMatrix(), True)
doc.recompute()
f1, f2, _v = canonical_faces(raw.Shape, skew)
count = len([o for o in doc.Objects if brackets.is_brackets(o)])

select()
brackets_ui.CreateBrackets().Activated()
check(messages and "two faces that touch the profiles" in messages[-1]
      and len([o for o in doc.Objects if brackets.is_brackets(o)]) == count, "command: no picks, instructions shown")
select([Picked(raw, [f"Face{f1}"])], [raw])
brackets_ui.CreateBrackets().Activated()
check("1 face(s) picked" in messages[-1] and len([o for o in doc.Objects if brackets.is_brackets(o)]) == count,
      "command: one face, refused with instructions")
select([Picked(lines)], [lines])
brackets_ui.CreateBrackets().Activated()
check(len([o for o in doc.Objects if brackets.is_brackets(o)]) == count and "two faces" in messages[-1],
      "command: a line object is not taken as the bracket")
frame_group = doc.addObject("App::DocumentObjectGroup", "Frame")
for p in ring:
    frame_group.addObject(p)
profile_link = doc.addObject("App::Link", "ProfileLink")
profile_link.LinkedObject = ring[0]
doc.recompute()
for picked in (frame_group, profile_link):
    messages.clear()
    select([Picked(picked)], [picked])
    brackets_ui.CreateBrackets().Activated()
    check(len([o for o in doc.Objects if brackets.is_brackets(o)]) == count and messages and "two faces" in messages[-1]
          and not shown, f"command: {picked.TypeId} holding the frame's profiles is not taken as the bracket")
select([Picked(part)], [part])
brackets_ui.CreateBrackets().Activated()
check(shown and shown[-1].LinkedObject == part and shown[-1].SourceFrame.isIdentity() and shown[-1].Count == 4,
      "command: a whole part without picks is used as modelled")

select([Picked(raw, [f"Face{f1}", f"Face{f2}"]), Picked(ring[0], ["Face3"])], [raw, ring[0]])
brackets_ui.CreateBrackets().Activated()
made = shown[-1] if shown else None
check(made is not None and brackets.is_brackets(made) and made.LinkedObject == raw
      and same_placement(made.SourceFrame, skew) and made.Count == 2,
      f"command: brackets at the joints of the selected profile, calibrated ({made and made.Count})")

select([Picked(raw, [f"Face{f1}", f"Face{f2}"])], [raw])
brackets_ui.CreateBrackets().Activated()
made = shown[-1]
check(made.Count == 4 and len(made.Joints) == 4 and made.AllJoints,
      f"command: all joints, also later ones, when none are selected ({made.Count})")

# Mis-set it, then pick the contact faces on its first placed bracket (a placed copy has
# the part's own face numbers).
made.SwapLegs = True
made.SourceFrame = App.Placement()
doc.recompute()
select([Picked(made, [f"0.Face{f1}", f"0.Face{f2}"])], [])
check(brackets_ui.CalibrateBracket().IsActive(), "calibrate: active with picks on a placed bracket")
brackets_ui.CalibrateBracket().Activated()
check(same_placement(made.SourceFrame, skew) and not made.SwapLegs and made.Count == 4,
      f"calibrate: picks on a placed bracket set the frame again ({made.SourceFrame})")
select([], [])
check(not brackets_ui.CalibrateBracket().IsActive(), "calibrate: inactive without a Brackets object")

print("\n%d failure(s)" % len(failures))

# A non-zero exit code lets CI see failures; os._exit skips FreeCAD's own exit handling.
sys.stdout.flush()
os._exit(1 if failures else 0)
