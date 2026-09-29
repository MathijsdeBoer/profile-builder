"""Headless test of bracket placement. Run with:  freecadcmd tests/freecad_brackets.py

A small L-shaped Part solid with slot keys stands in for a supplier's STEP
bracket. It is modelled in a skewed position, as imports are, so the
calibration has to find its frame.
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
lines = lines_object("CubeLines", segments)
doc.recompute()
cube = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(lines, f"Edge{i + 1}")) for i in range(12)]
doc.recompute()
cube_joints = joints.create_joints(doc, cube, "Butt", "Vertical")
doc.recompute()
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
check(not wrong and overlap < 1e-3 and clash < 1e-3, f"swap legs: still touching, no overlap ({wrong[:2]}, {overlap:.4f})")
br.SwapLegs = False

# A slot offset moves the keys out of the slots, so they hit the lips.
br.SlotOffset = 2.0
doc.recompute()
_wrong, overlap, _clash = fit_report(cube)
check(overlap > 1.0, f"slot offset shifts the brackets across the slot ({overlap:.2f} mm3 into the lips)")
br.SlotOffset = 0.0
doc.recompute()

# Bigger posts: the brackets follow, and the rails no longer close a corner between them.
corner.ThroughRule = "Vertical"  # undo the swap: posts run through everywhere again
for p in cube[8:]:
    p.Series = "30-8"
doc.recompute()
wrong, overlap, clash = fit_report(cube)
check(br.Count == 16, f"3030 posts: 16 brackets, none between the rails ({br.Count})")
check(not wrong and overlap < 1e-3 and clash < 1e-3, f"3030 posts: touching, no overlap ({wrong[:2]}, {overlap:.4f})")

# Stretching the sketch lines: the brackets follow.
segments = [((a[0] * 1.5, a[1], a[2]), (b[0] * 1.5, b[1], b[2])) for a, b in segments]
lines.Shape = Part.makeCompound([Part.makeLine(V(*a), V(*b)) for a, b in segments])
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

# A 2040 rail lying flat has two slots on top, neither in line with the 2020 post's slot: no
# brackets there, and a note says why.
goal[2].Columns = 2
doc.recompute()
check(gb.Count == 0 and any("do not line up" in n for n in gb.Notes), f"flat 2040 rail: slots do not line up ({gb.Notes})")
# Standing on edge, its top and bottom faces have one slot each, in line with the posts'.
goal[2].Columns, goal[2].Rows = 1, 2
doc.recompute()
wrong, overlap, clash = fit_report(goal)
heights = sorted({round(pl.Base.z, 3) for pl in gb.PlacementList})
check(gb.Count == 4 and not wrong and overlap < 1e-3 and heights == [380.0, 420.0],
      f"2040 rail on edge: brackets at its top and bottom faces ({gb.Count}, {heights})")

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
check(mb.isValid() and mb.Count == 0 and len(mb.Notes) == 4 and "miter" in mb.Notes[0], f"miter joints: noted ({mb.Notes})")
check(list(mb.VisibilityList) == [False] and Part.getShape(mb).isNull(), "no brackets: nothing stray is shown")
report = cutlist.build_report(doc)
check(not report.hardware and any("miter joint" in w for w in report.warnings), "miter joints: note in the cut list")
for j in ring_joints:
    j.Type = "Butt"
doc.recompute()
check(mb.Count == 4 and all(mb.VisibilityList) and len(Part.getShape(mb).Solids) == 4,
      f"butt joints again: 4 brackets, shown ({mb.Count}, {mb.VisibilityList})")

print("\n%d failure(s)" % len(failures))
