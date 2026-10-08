"""Headless feature test. Run with:  freecadcmd tests/freecad_smoke.py"""

import os
import sys
import tempfile

import freecad

# CI runners have no display: let Qt draw off screen, or creating a QApplication aborts the process.
# It is set here, not in the job, because FreeCAD's AppRun overrides QT_QPA_PLATFORM.
if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = os.getcwd()
# FreeCAD may already have loaded an installed copy of the workbench (for
# example through a link in its Mod folder) before this script runs. Drop it
# and put this checkout first, or a worktree would silently test other code.
for _name in [m for m in sys.modules if m == "freecad.profile_builder" or m.startswith("freecad.profile_builder.")]:
    del sys.modules[_name]
freecad.__path__.insert(0, os.path.join(ROOT, "freecad"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402
import Sketcher  # noqa: E402

from freecad.profile_builder import box_frame, cutlist, feature, joints, panels, pricing  # noqa: E402

_loaded = os.path.normcase(os.path.realpath(feature.__file__))
if not _loaded.startswith(os.path.normcase(os.path.realpath(ROOT))):
    raise SystemExit(f"testing the wrong copy of the workbench: {_loaded} is not under {ROOT}")
print(f"testing {os.path.dirname(_loaded)}")

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


doc = App.newDocument("pbtest")

p = feature.make_profile("20-6", 1, 2, 500, doc)
doc.recompute()
check(p.Shape.isValid() and p.Shape.Solids, "2040 builds")
check(p.Designation == "2040 (20-6)", f"designation {p.Designation}")
check(abs(p.Shape.BoundBox.XLength - 20) < 1e-6 and abs(p.Shape.BoundBox.YLength - 40) < 1e-6, "2040 size")
check(abs(p.OverallLength.Value - 500) < 1e-6, "overall length")
check(0.8 < p.MassPerMeter < 1.0, f"2040 mass/m {p.MassPerMeter}")

p.Series = "40-8"
doc.recompute()
check(abs(p.CellSize.Value - 40) < 1e-9 and p.Designation == "4080 (40-8)", "series change resets dims")

p.MiterStart = 45
p.MiterEnd = 45
doc.recompute()
check(p.Shape.isValid() and abs(p.OverallLength.Value - (500 + 40)) < 1e-4,
      f"45 deg miters: saw length {p.OverallLength.Value:.2f}")

p.ClosedTop = True
p.SlotStyle = "V-slot"
p.Anchor = "Bottom left"
doc.recompute()
bb = p.Shape.BoundBox
check(abs(bb.XMin) < 1e-6 and abs(bb.YMin) < 1e-6, f"bottom-left anchor {bb}")

sk = doc.addObject("Sketcher::SketchObject", "Frame")
pts = [App.Vector(0, 0, 0), App.Vector(800, 0, 0), App.Vector(800, 600, 0), App.Vector(0, 600, 0)]
for a, b in zip(pts, pts[1:] + pts[:1]):
    sk.addGeometry(Part.LineSegment(a, b))
doc.recompute()
on_edges = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(sk, f"Edge{i}")) for i in range(1, 5)]
doc.recompute()
check(all(o.Shape.isValid() for o in on_edges), "profiles on sketch edges")
check(abs(on_edges[0].Length.Value - 800) < 1e-6 and abs(on_edges[1].Length.Value - 600) < 1e-6,
      "edge lengths picked up")
e0 = on_edges[1].Shape.BoundBox
check(abs(e0.XMin - 790) < 1e-6 and abs(e0.YMax - 600) < 1e-6, f"edge placement {e0}")

on_edges[0].ExtendStart = -10
on_edges[0].ExtendEnd = 20
doc.recompute()
check(abs(on_edges[0].Length.Value - 810) < 1e-6, "extend start/end")

# Stretch the bottom edge (method renamed in FreeCAD 1.1).
(getattr(sk, "moveGeometry", None) or sk.movePoint)(0, 2, App.Vector(1000, 0, 0))
doc.recompute()
check(abs(on_edges[0].Length.Value - 1010) < 1e-6, f"follows sketch change: {on_edges[0].Length.Value}")

report = cutlist.build_report(doc)
pieces = report.piece_count
check(pieces == 5, f"cut list pieces {pieces}")
sheet = cutlist.write_spreadsheet(doc, report)
check(sheet.getContents("B2") in ("Qty", "'Qty"), f"spreadsheet header {sheet.getContents('B2')!r}")
csv_path = os.path.join(tempfile.gettempdir(), "pb_cutlist.csv")
cutlist.write_csv(report, csv_path)
check(os.path.getsize(csv_path) > 0, "csv export")

name = p.Name
path = os.path.join(tempfile.gettempdir(), "pbtest.FCStd")
doc.saveAs(path)
App.closeDocument(doc.Name)
doc = App.openDocument(path)
q = doc.getObject(name)
check(q.Series == "40-8" and q.SlotStyle == "V-slot" and q.ClosedTop, "properties survive reload")
q.Length = 700
doc.recompute()
check(q.Shape.isValid() and abs(q.Length.Value - 700) < 1e-9 and abs(q.CellSize.Value - 40) < 1e-9,
      "recompute after reload keeps custom state")

# Miter pivots around the section centre, also with an offset anchor.
r = feature.make_profile("20-6", 1, 1, 300, doc, MiterStart=30, MiterAcross="Y", Anchor="Bottom center")
doc.recompute()
bb = r.Shape.BoundBox
check(r.Shape.isValid() and abs(bb.YMin) < 1e-6 and abs(bb.XMin + 10) < 1e-6, f"anchor + miter {bb}")
check(abs(r.OverallLength.Value - (300 + 10 * 0.57735)) < 1e-3,
      f"30 deg miter saw length {r.OverallLength.Value:.3f}")

# ---- catalog: every series, size, slot style and weight class builds ----------

from freecad.profile_builder import geometry, profiles  # noqa: E402

bad = []
count = 0
for key, series in profiles.SERIES.items():
    for weight in profiles.WEIGHTS:
        for style in profiles.SLOT_STYLES:
            for cols, rows in series.sizes:
                count += 1
                try:
                    solid = geometry.make_profile(series.dimensions(weight), cols, rows, 50, style)
                    if not solid.isValid() or len(solid.Solids) != 1:
                        bad.append((key, weight, style, cols, rows))
                except Exception as e:  # noqa: BLE001
                    bad.append((key, weight, style, cols, rows, str(e)))
check(not bad, f"catalog: {count} variants build ({bad[:3]})")

w = feature.make_profile("40-8", 1, 1, 100, doc)
doc.recompute()
standard_mass = w.MassPerMeter
w.Weight = "Ultralight"
doc.recompute()
check(w.ChamberWall.Value > 0 and w.BoreDiameter.Value > 6.8 and w.MassPerMeter < standard_mass,
      f"weight: ultralight is hollower ({w.MassPerMeter:.3f} < {standard_mass:.3f} kg/m)")
check(w.Designation == "4040 Ultralight (40-8)", f"weight in designation: {w.Designation}")
w.Weight = "Heavy"
doc.recompute()
check(w.MassPerMeter > standard_mass and w.ChamberWall.Value == 0, "weight: heavy is solid")
doc.removeObject(w.Name)

# ---- joints: a 400 mm cube of 2020 on centre lines --------------------------

def lines_object(name, segments):
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = Part.makeCompound([Part.makeLine(App.Vector(*a), App.Vector(*b)) for a, b in segments])
    return obj


cube_doc = App.newDocument("cube")
doc = cube_doc
skeleton, cube, created, warnings = box_frame.make_box(
    doc, width=400, depth=400, height=400, size_mode="Centre lines")
lines = skeleton
check(len(created) == 8, f"cube: 8 corner joints ({len(created)})")
check(not warnings, f"cube: no joint warnings ({warnings})")
lengths = sorted(round(p.Length.Value, 3) for p in cube)
check(lengths == [380.0] * 8 + [420.0] * 4, f"cube: rails 380, posts 420 ({lengths})")
check(all(p.Shape.isValid() for p in cube), "cube: all valid")
# The frame is a 420 mm cube and the pieces do not overlap.
bb = Part.makeCompound([p.Shape for p in cube]).BoundBox
check(abs(bb.XLength - 420) < 1e-6 and abs(bb.ZLength - 420) < 1e-6, f"cube: outside 420 ({bb})")
overlap = sum(cube[i].Shape.common(cube[j].Shape).Volume for i in range(12) for j in range(i + 1, 12))
check(overlap < 1e-3, f"cube: no overlapping profiles ({overlap:.3f} mm3)")

# Changing the post size updates the rails that butt into them.
for p in cube[8:]:
    p.Series = "30-8"
doc.recompute()
lengths = sorted(round(p.Length.Value, 3) for p in cube)
check(lengths == [370.0] * 8 + [420.0] * 4, f"cube: 3030 posts -> rails 370 ({lengths})")

# Stretching the lines keeps the joints right.
skeleton.Width = 600
doc.recompute()
x_rails = sorted(round(p.Length.Value, 3) for p in cube if abs(feature.member_frame(p).z.x) > 0.9)
check(x_rails == [570.0] * 4, f"cube: stretched X rails 570 ({x_rails})")

# ---- box generator: outside, inside-clear and centre-line sizing -------------

box_doc = App.newDocument("boxoutside")
doc = box_doc
box_skeleton, box_members, box_joints, warnings = box_frame.make_box(
    doc, width=600, depth=600, height=700, size_mode="Outside")


def box_extents(members):
    bounds = Part.makeCompound([member.Shape for member in members]).BoundBox
    return bounds.XLength, bounds.YLength, bounds.ZLength


check(len(box_joints) == 8 and not warnings,
      f"outside box: 8 joints and no warnings ({len(box_joints)}, {warnings})")
check(all(abs(a - b) < 1e-6 for a, b in zip(box_extents(box_members), (600, 600, 700))),
      f"outside box: 600 x 600 x 700 ({box_extents(box_members)})")
edge9 = box_skeleton.Shape.Edges[8]
check((edge9.Vertexes[0].Point - App.Vector(0, 0, 0)).Length < 1e-6,
      "box skeleton: Edge9 is the post at the origin")

for post in box_members[8:]:
    post.Series = "30-8"
doc.recompute()
check(all(abs(a - b) < 1e-6 for a, b in zip(box_extents(box_members), (600, 600, 700))),
      f"outside box: 3030 posts keep the requested size ({box_extents(box_members)})")

for rail in box_members[:8]:
    rail.Series = "30-8"
doc.recompute()
check(all(abs(a - b) < 1e-6 for a, b in zip(box_extents(box_members), (600, 600, 700))),
      f"outside box: 3030 rails keep the requested size ({box_extents(box_members)})")

box_skeleton.SizeMode = "Inside clear"
box_skeleton.Width = 400
box_skeleton.Depth = 350
box_skeleton.Height = 500
doc.recompute()
line_bounds = box_skeleton.Shape.BoundBox
check(all(abs(a - b) < 1e-6 for a, b in
          zip((line_bounds.XLength, line_bounds.YLength, line_bounds.ZLength), (430, 380, 530))),
      f"inside-clear box: correct centre-line spans ({line_bounds})")
check(all(abs(a - b) < 1e-6 for a, b in zip(box_extents(box_members), (460, 410, 560))),
      f"inside-clear box: 400 x 350 x 500 clear ({box_extents(box_members)})")

box_skeleton.SizeMode = "Centre lines"
doc.recompute()
line_bounds = box_skeleton.Shape.BoundBox
check(all(abs(a - b) < 1e-6 for a, b in
          zip((line_bounds.XLength, line_bounds.YLength, line_bounds.ZLength), (400, 350, 500))),
      f"centre-line box: exact requested spans ({line_bounds})")
with tempfile.TemporaryDirectory() as temp_dir:
    saved_box = os.path.join(temp_dir, "box.FCStd")
    box_doc.saveAs(saved_box)
    App.closeDocument(box_doc.Name)
    doc = App.openDocument(saved_box)
    restored_skeleton = next(obj for obj in doc.Objects if
                             getattr(getattr(obj, "Proxy", None), "Type", None) == "ProfileBuilder::Skeleton")
    restored_members = [obj for obj in doc.Objects if feature.is_profile(obj)]
    doc.recompute()
    check(len(restored_members) == 12 and len(
        [obj for obj in doc.Objects if joints.is_joint(obj)]) == 8,
        "box frame: skeleton, profiles and joints survive save and reload")
    restored_edge9 = next(feature.path_edge(obj) for obj in restored_members
                          if obj.PathEdge[1][0] == "Edge9")
    check((restored_edge9.Vertexes[0].Point - App.Vector(0, 0, 0)).Length < 1e-6,
          "box frame: Edge9 reference survives save and reload")
    App.closeDocument(doc.Name)

# ---- box generator: one side heavier, offsets, colliding rails, a failed skeleton -----

from freecad.profile_builder import check as frame_check, skeleton as skeleton_module  # noqa: E402

side_doc = App.newDocument("boxsides")
doc = side_doc
side_skeleton, side_members, _side_joints, _side_warnings = box_frame.make_box(
    doc, width=600, depth=600, height=700, size_mode="Outside")
for rail in side_members[:4]:  # Edge1-4: the bottom ring
    rail.Rows = 2
doc.recompute()
check(all(abs(a - b) < 1e-6 for a, b in zip(box_extents(side_members), (600, 600, 700))),
      f"outside box: 2040 bottom rails only keep the requested size ({box_extents(side_members)})")
for post in side_members[8:10]:  # Edge9 and Edge10: the posts at y = 0
    post.Series = "30-8"
doc.recompute()
check(all(abs(a - b) < 1e-6 for a, b in zip(box_extents(side_members), (600, 600, 700))),
      f"outside box: 3030 front posts only keep the requested size ({box_extents(side_members)})")
check(not frame_check.box_frames(doc), "box frame check: no size warning while the size holds")

side_skeleton.SizeMode = "Inside clear"
side_skeleton.Width = 400
side_skeleton.Depth = 400
side_skeleton.Height = 500
doc.recompute()
side_boxes = [member.Shape.BoundBox for member in side_members]
clear_y = (min(side_boxes[i].YMin for i in (2, 6, 10, 11)) - max(side_boxes[i].YMax for i in (0, 4, 8, 9)))
clear_z = min(box.ZMin for box in side_boxes[4:8]) - max(box.ZMax for box in side_boxes[:4])
check(abs(clear_y - 400) < 1e-6 and abs(clear_z - 500) < 1e-6,
      f"inside-clear box: 400 deep and 500 high clear with heavier front posts and bottom rails "
      f"({clear_y:.3f}, {clear_z:.3f})")
side_measured = skeleton_module.measured_size(side_skeleton)
check(all(abs(a - b) < 1e-6 for a, b in zip(side_measured, (400, 400, 500))),
      f"inside-clear box: measured clear size ({side_measured})")

# A section offset (Align slots) moves a post outward; the skeleton cannot follow, so the check warns.
side_skeleton.SizeMode = "Outside"
side_skeleton.Width = 600
side_skeleton.Depth = 600
side_skeleton.Height = 700
doc.recompute()
feature.ensure_section_offset_properties(side_members[8])
side_members[8].SectionOffsetX = -30  # local X is world X for the post at the origin
doc.recompute()
size_warnings = [f for f in frame_check.box_frames(doc) if f.severity == "Warning"]
check(abs(box_extents(side_members)[0] - 630) < 1e-6 and len(size_warnings) == 1
      and side_skeleton.Name in size_warnings[0].objects,
      f"box frame check: a section offset that changes the outside size is reported "
      f"({box_extents(side_members)}, {ascii(size_warnings)})")
side_members[8].SectionOffsetX = 0
doc.recompute()

# Rails wider than the posts both ways would collide at all eight corners.
objects_before = len(doc.Objects)
try:
    box_frame.make_box(doc, 600, 600, 700, "Outside", rail_cols=2, rail_rows=1)
    collided = False
except ValueError:
    collided = True
check(collided and len(doc.Objects) == objects_before,
      "box frame: rails wider than the posts are refused before anything is created")

# A skeleton that fails keeps its old lines: its profiles must not pass as up to date.
side_skeleton.Width = 15  # expected traceback: "Outside dimensions must exceed the section sizes"
doc.recompute()
side_report = cutlist.build_report(doc)
side_broken = frame_check.broken(doc)
check(not side_skeleton.isValid() and all(feature.problem(member) for member in side_members)
      and len(side_report.errors) >= 12 and len(side_broken) >= 12,
      f"failed skeleton: its 12 profiles are reported ({len(side_report.errors)} errors, "
      f"{len(side_broken)} broken)")
App.closeDocument(side_doc.Name)

# The task panel keeps the exact sizes it was filled with, and reads typed text in the unit shown.
try:
    import re  # noqa: E402
    from PySide import QtWidgets  # noqa: E402
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from freecad.profile_builder import box_frame_ui  # noqa: E402
    original_schema = App.Units.getSchema()
    try:
        for schema, schema_name in enumerate(App.Units.listSchemas()):
            App.Units.setSchema(schema)
            panel_doc = App.newDocument(f"boxpanel{schema}")
            App.setActiveDocument(panel_doc.Name)
            panel = box_frame_ui.BoxFrameTaskPanel()
            wanted = (panel.defaults["width"], panel.defaults["depth"], panel.defaults["height"])
            accepted = panel.apply()
            got = (panel.skeleton.Width.Value, panel.skeleton.Depth.Value, panel.skeleton.Height.Value)
            check(accepted and all(abs(a - b) < 1e-9 for a, b in zip(got, wanted)),
                  f"box panel ({schema_name}): untouched sizes stay exact ({got}, {ascii(panel.info.text()[:80])})")
            shown = panel.width.text()
            number = re.match(r"[0-9.,]+", shown).group(0)
            unit = shown[len(number):]
            if not re.search(r"[0-9]", unit):  # the number the user sees, typed without its unit
                panel.width.setText(number)
                panel.apply()
                typed = App.Units.Quantity(number.replace(",", ".") + unit).Value
                check(abs(panel.skeleton.Width.Value - typed) < 1e-6,
                      f"box panel ({schema_name}): a bare {ascii(number)} is read in the unit shown, "
                      f"{ascii(unit.strip())} ({panel.skeleton.Width.Value:.4f} mm, wanted {typed:.4f})")
            else:  # feet and inches with a fraction: 2' 3" + 1/2"
                panel.width.setText("2' 3\" + 1/2\"")
                accepted = panel.apply()
                check(accepted and abs(panel.skeleton.Width.Value - 698.5) < 1e-6,
                      f"box panel ({schema_name}): feet, inches and a fraction are read "
                      f"({panel.skeleton.Width.Value:.4f} mm)")
            panel._timer.stop()
            panel_doc.abortTransaction()
            App.closeDocument(panel_doc.Name)
    finally:
        App.Units.setSchema(original_schema)

    panel_doc = App.newDocument("boxpanelwide")
    App.setActiveDocument(panel_doc.Name)
    panel = box_frame_ui.BoxFrameTaskPanel()
    rails_before = [(rail.Series, rail.Columns, rail.Rows) for rail in panel.rails]
    for combo, data in ((panel.post_series, "20-6"), (panel.post_size, "1x1"),
                        (panel.rail_series, "20-6"), (panel.rail_size, "2x1")):
        combo.setCurrentIndex(combo.findData(data))
    accepted = panel.apply()
    check(not accepted and "collide" in panel.info.text()
          and [(rail.Series, rail.Columns, rail.Rows) for rail in panel.rails] == rails_before,
          f"box panel: 2040 rails on side on 2020 posts are refused ({ascii(panel.info.text()[:80])})")
    panel._timer.stop()
    panel_doc.abortTransaction()
    App.closeDocument(panel_doc.Name)
except ImportError as e:
    check(False, f"box panel test could not run: {e}")

# ---- choosing which profiles run through: a 400 x 400 square of 2040 -----------

square_doc = App.newDocument("square")
doc = square_doc
sq = [(0, 0, 0), (400, 0, 0), (400, 400, 0), (0, 400, 0)]
sq_lines = lines_object("Square", list(zip(sq, sq[1:] + sq[:1])))
doc.recompute()
sides = [feature.make_profile("20-6", 1, 2, 100, doc, edge=(sq_lines, f"Edge{i + 1}")) for i in range(4)]
doc.recompute()
joints.create_joints(doc, sides, "Butt", "Longest")
doc.recompute()


def side_lengths():
    """Lengths of the X sides and the Y sides."""
    xs = sorted(round(p.Length.Value, 3) for p in sides if abs(feature.member_frame(p).z.x) > 0.9)
    ys = sorted(round(p.Length.Value, 3) for p in sides if abs(feature.member_frame(p).z.y) > 0.9)
    return xs, ys


check(side_lengths() == ([420.0, 420.0], [380.0, 380.0]), f"square: equal sides, X runs through {side_lengths()}")
y_sides = [p for p in sides if abs(feature.member_frame(p).z.y) > 0.9]
joints.set_runs_through(y_sides)
doc.recompute()
check(side_lengths() == ([380.0, 380.0], [420.0, 420.0]), f"square: Run through on Y sides {side_lengths()}")
corner = sides[0].StartJoint
joints.swap(corner)
doc.recompute()
xs, ys = side_lengths()
check(sorted(xs + ys) == [380.0, 400.0, 400.0, 420.0], f"square: swapping one corner {side_lengths()}")
for p in sides:
    p.JointRole = "Auto"
for j in [o for o in doc.Objects if joints.is_joint(o)]:
    j.ThroughRule = "Along Y"
doc.recompute()
check(side_lengths() == ([380.0, 380.0], [420.0, 420.0]), f"square: rule Along Y {side_lengths()}")

# ---- miter corners and a T-junction in a flat frame --------------------------

frame_doc = App.newDocument("frame")
doc = frame_doc
W, H = 600, 400
rect = [(0, 0, 0), (W, 0, 0), (W, H, 0), (0, H, 0)]
segs = list(zip(rect, rect[1:] + rect[:1])) + [((W / 2, 0, 0), (W / 2, H, 0))]
flat = lines_object("FrameLines", segs)
doc.recompute()
ring = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(flat, f"Edge{i + 1}")) for i in range(4)]
doc.recompute()
created = joints.create_joints(doc, ring, "Miter")
doc.recompute()
saw = sorted(round(p.OverallLength.Value, 3) for p in ring)
check(len(created) == 4 and saw == [420.0, 420.0, 620.0, 620.0], f"miter: saw lengths ({saw})")
check(all(abs(abs(p.MiterStart.Value) - 45) < 1e-6 and abs(abs(p.MiterEnd.Value) - 45) < 1e-6 for p in ring),
      "miter: 45 degree ends")
overlap = sum(ring[i].Shape.common(ring[j].Shape).Volume for i in range(4) for j in range(i + 1, 4))
check(overlap < 1e-3, f"miter: no overlap ({overlap:.3f} mm3)")
outer = Part.makeCompound([p.Shape for p in ring]).BoundBox
check(abs(outer.XLength - 620) < 1e-6 and abs(outer.YLength - 420) < 1e-6, "miter: outside 620 x 420")

# A middle bar ending on the (mitered) bottom and top rails: T-junctions.
bar = feature.make_profile("20-6", 1, 1, 100, doc, edge=(flat, "Edge5"))
doc.recompute()
created = joints.create_joints(doc, [bar] + ring)
doc.recompute()
check(len(created) == 2 and abs(bar.Length.Value - 380) < 1e-6, f"T-junction: bar 380 ({bar.Length.Value})")

# ---- panels ------------------------------------------------------------------

side = panels.make_panel(doc, ring)
doc.recompute()
check(side.isValid() and abs(side.Width.Value - 591.2) < 1e-6 and abs(side.Height.Value - 391.2) < 1e-6,
      f"panel in slot: 591.2 x 391.2 ({side.Width.Value:.2f} x {side.Height.Value:.2f})")
cover = panels.make_panel(doc, ring, Mount="On face", Margin=1)
doc.recompute()
check(cover.isValid() and abs(cover.Width.Value - 618) < 1e-6 and abs(cover.Shape.BoundBox.ZMin - 10) < 1e-6,
      f"panel on face: 618 wide on top ({cover.Width.Value:.2f}, z {cover.Shape.BoundBox.ZMin:.2f})")
thick = panels.make_panel(doc, ring, Thickness=8)
doc.recompute()
check(not thick.isValid(), "panel: too thick for the slot is an error")
doc.removeObject(thick.Name)

# ---- pricing, stock plan and costs --------------------------------------------

settings = pricing.get_settings(doc, create=True)
settings.ProfilePrices = {"2020 (20-6)": "10"}
settings.SheetPrices = {"Acrylic 3 mm": "40"}
settings.DeliveryFlat = 15
settings.DeliveryPerKg = 1
settings.TaxPercent = 21
settings.CutCost = 0.5
report = cutlist.build_report(doc)
costs = dict(report.summary)
saw_total = 2 * 620 + 2 * 420 + 380
check(abs(costs["Profiles"] - saw_total / 1000 * 10) < 0.01, f"cut to size profile cost {costs['Profiles']}")
check(abs(costs["Cutting"] - 2.5) < 1e-9, "cutting cost per piece")
sheets = 0.5912 * 0.3912 * 40 + 0.618 * 0.418 * 40
check(abs(costs["Sheets"] - sheets) < 0.02, f"sheet cost {costs['Sheets']}")
check(abs(report.total - sum(v for k, v in report.summary[:-2]) * 1.21) < 0.02, "tax on the total")

settings.PurchaseMode = "Stock bars"
settings.StockLength = 2000
report = cutlist.build_report(doc)
check(len(report.stock) == 2, f"stock plan: 2 bars of 2 m ({report.stock})")
check(abs(dict(report.summary)["Profiles"] - 40) < 1e-9, "stock bars: pay for whole bars")
cutlist.write_spreadsheet(doc, report)

first = ring[0].Name
path = os.path.join(tempfile.gettempdir(), "pbframe.FCStd")
doc.saveAs(path)
App.closeDocument(doc.Name)
doc = App.openDocument(path)
doc.getObject(first).touch()
doc.recompute()
check(all(o.isValid() for o in doc.Objects), "frame reloads and recomputes cleanly")
check(pricing.get_settings(doc).ProfilePrices["2020 (20-6)"] == "10", "prices saved in the document")

# ---- regressions: bugs found in the 2026-09-28 review ---------------------------

fix_doc = App.newDocument("fixes")
doc = fix_doc


def ring_of(name, w, h, joint_type, at=(0, 0)):
    x, y = at
    pts = [(x, y, 0), (x + w, y, 0), (x + w, y + h, 0), (x, y + h, 0)]
    lines = lines_object(name, list(zip(pts, pts[1:] + pts[:1])))
    doc.recompute()
    members = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(lines, f"Edge{i + 1}")) for i in range(4)]
    doc.recompute()
    joints.create_joints(doc, members, joint_type, "Longest")
    doc.recompute()
    return lines, members


# Mirror-identical mitered pieces share one row (the signs follow the drawing direction).
_lines, mring = ring_of("MiterRing", 400, 300, "Miter")
rows = cutlist.build_report(doc).pieces
PIECE = cutlist.PIECE_HEADER
check(sorted((r[PIECE.index("Qty")], r[PIECE.index("Saw length (mm)")]) for r in rows) == [(2, 320.0), (2, 420.0)],
      f"miter ring: 2 rows of 2 identical pieces ({[(r[1], r[4], r[5], r[6]) for r in rows]})")
check(all(r[PIECE.index("Miter start (°)")] == 45 and r[PIECE.index("Miter end (°)")] == 45 for r in rows),
      "miter ring: shown as 45 / 45")

# Deleting a miter joint puts the ends back to square cuts.
corner = mring[0].StartJoint
neighbours = [(p, e) for p, e in joints.ends_of(corner)]
doc.removeObject(corner.Name)
doc.recompute()
check(all(getattr(p, f"Miter{e}").Value == 0 and not getattr(p, f"{e}MiterFromJoint") for p, e in neighbours),
      f"deleted miter joint: square ends again ({[(p.Label, e, getattr(p, f'Miter{e}').Value) for p, e in neighbours]})")
for p in mring:
    doc.removeObject(p.Name)
for j in [o for o in doc.Objects if joints.is_joint(o)]:
    doc.removeObject(j.Name)
doc.recompute()

# A hand-picked (swapped) corner survives renaming the profiles, also after the joint recomputes.
_lines, bring = ring_of("ButtRing", 400, 400, "Butt")
corner = bring[0].StartJoint
before = sorted(round(p.Length.Value, 3) for p in bring)
joints.swap(corner)
doc.recompute()
swapped = {p.Name: round(p.Length.Value, 3) for p in bring}
for i, p in enumerate(bring):
    p.Label = f"Side {chr(65 + i)}"
doc.recompute()
corner.touch()
for p in bring:
    p.touch()
doc.recompute()
after = {p.Name: round(p.Length.Value, 3) for p in bring}
check(after == swapped and sorted(swapped.values()) != before,
      f"swap survives rename ({swapped} -> {after})")
chosen = doc.getObject(corner.ThroughName)
check(chosen is not None and corner.Through == chosen.Label, f"joint shows the renamed profile ({corner.Through})")

# A document from before ThroughName (label only) picks the name up on recompute.
corner.ThroughName = ""
corner.touch()
doc.recompute()
check(corner.ThroughName == chosen.Name, "legacy manual joint gets ThroughName")

# Broken profiles are reported instead of silently missing from the cut list.
bad = feature.make_profile("20-6", 1, 1, 300, doc)
doc.recompute()
bad.SlotOpening = 30  # wider than the profile
doc.recompute()
report = cutlist.build_report(doc)
check(not bad.isValid() and report.errors and bad.Label in report.errors[0], f"broken profile reported ({report.errors})")
check(report.summary[-1][0].startswith("Total, incomplete"), "total marked incomplete")
check(bad.Label not in " ".join(str(r) for r in report.pieces), "broken profile not counted")
doc.removeObject(bad.Name)
doc.recompute()

# Piece marks: in the cut list, the stock plan and on the objects, without recomputing them.
settings = pricing.get_settings(doc, create=True)
settings.PurchaseMode = "Stock bars"
report = cutlist.build_report(doc)
marks = [r[0] for r in report.pieces]
check(marks == sorted(marks) and marks[0] == "A1", f"piece marks {marks}")
check(all(":" in r[3] for r in report.stock) and "A1: " in report.stock[0][3], f"stock plan shows marks {report.stock}")
cutlist.apply_marks(doc, report)
check(all(p.PieceMark in marks and "Touched" not in p.State for p in bring), "marks written without touching")
check(all(p.Label2 == f"Mark {p.PieceMark}" for p in bring), "marks shown in the tree description")

# CSV for Excel with a decimal comma.
report = cutlist.build_report(doc)
csv_path = os.path.join(tempfile.gettempdir(), "pb_cutlist_semicolon.csv")
cutlist.write_csv(report, csv_path, delimiter=";", decimal=",")
raw = open(csv_path, "rb").read()
text = raw.decode("utf-8-sig")
check(raw.startswith(b"\xef\xbb\xbf") and "Mark;Qty;Product" in text and "Saw length (mm)" in text,
      "semicolon CSV with byte order mark")
import re  # noqa: E402
cells = [c for line in text.splitlines() for c in line.split(";")]
check(any(re.fullmatch(r"\d+,\d+", c) for c in cells) and not any(re.fullmatch(r"\d+\.\d+", c) for c in cells),
      f"decimal comma in numbers ({[c for c in cells if re.fullmatch(r'[0-9.,]+', c)][:6]})")

# A profile whose sketch line was deleted says so.
sk = doc.addObject("Sketcher::SketchObject", "Deleted")
sk.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(100, 0, 0)))
sk.addGeometry(Part.LineSegment(App.Vector(0, 50, 0), App.Vector(100, 50, 0)))
doc.recompute()
orphans = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(sk, f"Edge{i}")) for i in (1, 2)]
doc.recompute()
sk.delGeometry(0)
doc.recompute()
invalid = [p for p in orphans if not p.isValid()]
status = invalid[0].getStatusString() if invalid else ""
check(len(invalid) == 1 and "no longer exists" in status, f"deleted line: clear message ({status!r})")
for p in orphans:
    doc.removeObject(p.Name)

# Ends that nearly meet are reported.
near = lines_object("NearMiss", [((0, 0, 0), (200, 0, 0)), ((200.2, 0, 0), (200.2, 200, 0)),
                                 ((100, 0.4, 0), (100, 150, 0))])
doc.recompute()
nm = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(near, f"Edge{i}")) for i in (1, 2, 3)]
doc.recompute()
warnings = []
joints.create_joints(doc, nm, warnings=warnings)
check(len(warnings) == 2 and "0.20 mm apart" in warnings[0] and "0.40 mm from" in warnings[1],
      f"near misses reported ({warnings})")

# Panel material sets density and expansion; the thermal fit is checked.
lines = lines_object("PanelRing", [((0, 0, 0), (600, 0, 0)), ((600, 0, 0), (600, 400, 0)),
                                   ((600, 400, 0), (0, 400, 0)), ((0, 400, 0), (0, 0, 0))])
doc.recompute()
pring = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(lines, f"Edge{i + 1}")) for i in range(4)]
doc.recompute()
sheet = panels.make_panel(doc, pring)
doc.recompute()
check(abs(sheet.CutTolerance.Value - 0.2) < 1e-9 and panels.thermal_fit(sheet)[1] is not None,
      "600 mm acrylic at 50 °C is too tight with a ±0.2 mm cut")
sheet.CutTolerance = 0
check(abs(sheet.Expansion - 70) < 1e-9 and panels.thermal_fit(sheet)[1] is None, "acrylic at 50 °C fits an exact cut")
sheet.Material = "Dibond 3 mm"
check(abs(sheet.Density - 1.27) < 1e-9 and abs(sheet.Expansion - 24) < 1e-9, "Dibond sets density and expansion")
sheet.Material = "Acrylic clear"
sheet.MaxTemperature = 80
doc.recompute()
need, warning = panels.thermal_fit(sheet)
check(warning is not None and need > sheet.Clearance.Value, f"hot acrylic too tight ({need:.2f} mm)")
check(any("needs" in w for w in cutlist.build_report(doc).warnings), "thermal warning in the report")

# Section properties of the modelled section.
s2020 = feature.make_profile("20-6", 1, 1, 100, doc)
s2040 = feature.make_profile("20-6", 1, 2, 100, doc)
doc.recompute()
check(abs(s2020.Ix - s2020.Iy) < 1e-6 and 0.6 < s2020.Ix < 0.9, f"2020 Ix = Iy = {s2020.Ix} cm4")
check(abs(s2040.Ix / s2040.Iy - 3.49) < 0.05 and s2040.Wx > s2040.Wy, f"2040 on edge 3.5x stiffer ({s2040.Ix}/{s2040.Iy})")

# The section cache hands out independent copies.
d = profiles.SERIES["40-8"].dimensions("Light")
geometry.clear_section_cache()
import time  # noqa: E402
t0 = time.perf_counter()
first_face = geometry.make_section(d, 1, 1)
t1 = time.perf_counter()
first_face.translate(App.Vector(1000, 0, 0))
again = geometry.make_section(d, 1, 1)
t2 = time.perf_counter()
check(abs(again.BoundBox.XMin + 20) < 1e-6, "cached section is not shared")
check(t2 - t1 < (t1 - t0) / 3, f"cache hit is fast ({(t1 - t0) * 1000:.1f} -> {(t2 - t1) * 1000:.2f} ms)")

# ---- regressions from the review of those fixes ---------------------------------

# The decimal-comma CSV keeps full precision.
report = cutlist.build_report(doc)
report.summary[-1] = ("Total", 1233456.78)
cutlist.write_csv(report, csv_path, delimiter=";", decimal=",")
check("Total;1233456,78" in open(csv_path, encoding="utf-8-sig").read(), "decimal-comma CSV keeps cents")

# Material names match on whole words, trade names first.
cases = {"Clear glass": 9.0, "Aluminium Dibond": 24.0, "aluminum composite": 24.0, "Aluminum sheet": 23.1,
         "Acrylic (PMMA) 3 mm": 70.0, "Lexan 4 mm": 65.0, "PETG": 60.0, "Mystery board": None}
got = {k: (panels.material_data(k) or (None, None))[1] for k in cases}
check(got == cases, f"material names ({got})")

# The Panel dialog keeps the density and expansion that a new material sets.
try:
    from PySide import QtWidgets  # noqa: E402
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from freecad.profile_builder import simple_panel  # noqa: E402
    dialog = simple_panel.PropertyTaskPanel(sheet, panels.PANEL_FIELDS, "Panel", panels.panel_info)
    dialog.widgets["Material"].setText("Glass")
    dialog.apply()
    check(abs(sheet.Density - 2.5) < 1e-9 and abs(sheet.Expansion - 9) < 1e-9
          and abs(dialog.widgets["Density"].value() - 2.5) < 1e-9,
          f"panel dialog: glass sets density and expansion ({sheet.Density}, {sheet.Expansion})")
    dialog.widgets["Density"].setValue(2.45)  # the user's own value survives the next apply
    dialog.apply()
    check(abs(sheet.Density - 2.45) < 1e-9 and sheet.Material == "Glass", "panel dialog: typed density kept")
    doc.abortTransaction()
except ImportError as e:
    check(False, f"panel dialog test could not run: {e}")

# Documents saved by earlier versions (see tests/fixtures/make_legacy_fixture.py).
fixture = os.path.join(ROOT, "tests", "fixtures")
import json  # noqa: E402
import shutil  # noqa: E402


def check_legacy(tag):
    expected = json.load(open(os.path.join(fixture, f"{tag}.json"), encoding="utf-8"))
    legacy_path = os.path.join(tempfile.gettempdir(), f"pb_{tag}.FCStd")
    shutil.copy(os.path.join(fixture, f"{tag}.FCStd"), legacy_path)
    doc = App.openDocument(legacy_path)
    first = doc.getObject(list(expected["lengths"])[0])
    check("Ix" in first.PropertiesList, f"{tag}: new properties added on open")
    # Pass 1: open and make a cut list straight away.
    probe = doc.getObject(list(expected["miters"])[0])
    probe.Ix, probe.MiterStartAxis = 0.0, ""
    check(feature.needs_refresh(probe), f"{tag}: missing outputs are detected")
    cutlist.recompute_if_needed(doc)
    check(all(doc.getObject(n).Ix > 0 for n in expected["lengths"]), f"{tag}: cut list refreshes section properties")
    check(all(doc.getObject(n).MiterStartAxis for n in expected["miters"]), f"{tag}: cut list refreshes miter axes")
    App.closeDocument(doc.Name)
    shutil.copy(os.path.join(fixture, f"{tag}.FCStd"), legacy_path)
    # Pass 2: rename the hand-picked profile before anything recomputes.
    doc = App.openDocument(legacy_path)
    swapped = doc.getObject(expected["swapped_joint"])
    chosen = [o for o in doc.Objects if o.Label == expected["through"]][0]
    check(swapped.ThroughName == chosen.Name, f"{tag}: manual joint choice resolved to a name on open")
    for name, props in expected.get("custom", {}).items():
        obj = doc.getObject(name)
        kept = {p: getattr(obj, p).Value for p in props}
        check(all(abs(kept[p] - v) < 1e-9 for p, v in props.items()), f"{tag}: custom dimensions kept ({kept})")
    chosen.Label = "Renamed before any recompute"
    cutlist.recompute_if_needed(doc)
    lengths = {n: round(doc.getObject(n).Length.Value, 6) for n in expected["lengths"]}
    check(lengths == expected["lengths"], f"{tag}: same lengths after rename and recompute ({lengths})")
    saw = {n: round(doc.getObject(n).OverallLength.Value, 6) for n in expected["saw"]}
    check(saw == expected["saw"], f"{tag}: same saw lengths")
    for name, props in expected.get("custom", {}).items():
        obj = doc.getObject(name)
        check(all(abs(getattr(obj, p).Value - v) < 1e-9 for p, v in props.items()),
              f"{tag}: custom dimensions survive recompute")
    check(all(doc.getObject(n).Ix > 0 for n in expected["lengths"]), f"{tag}: section properties filled in")
    frame = [doc.getObject(n) for n in expected["miters"]]
    check(all(p.MiterStartAxis and p.MiterEndAxis for p in frame), f"{tag}: miter axes filled in")
    report = cutlist.build_report(doc)
    frame_rows = [r for r in report.pieces if r[PIECE.index("Saw length (mm)")] in (220.0, 320.0)]
    check(len(frame_rows) == 2 and all(r[PIECE.index("Qty")] == 2 for r in frame_rows), f"{tag}: frame pieces grouped")
    check(not report.errors, f"{tag}: no errors in the cut list ({report.errors})")
    glass = doc.getObject(expected["panel"])
    check(abs(glass.Density - 2.4) < 1e-9 and abs(glass.Expansion - 9) < 1e-9,
          f"{tag}: panel keeps the typed density, expansion from the material ({glass.Density}, {glass.Expansion})")
    check([round(glass.Width.Value, 6), round(glass.Height.Value, 6)] == expected["panel_size"], f"{tag}: panel size")
    corner = frame[0].StartJoint
    ends = joints.ends_of(corner)
    doc.removeObject(corner.Name)
    doc.recompute()
    check(all(getattr(p, f"Miter{e}").Value == 0 for p, e in ends), f"{tag}: removing a miter joint squares the ends")
    check(all(o.isValid() for o in doc.Objects), f"{tag}: everything valid")
    App.closeDocument(doc.Name)


for tag in ("legacy_8733122", "legacy_ead3f7d"):
    check_legacy(tag)

# ---- regressions from the second review round -----------------------------------

doc = App.newDocument("round2")

# [0] A vertical mitered square: 1x2 rails and 2x1 ("on side") posts are identical pieces.
pts = [(0, 0, 0), (400, 0, 0), (400, 0, 400), (0, 0, 400)]
xz = lines_object("XZ", list(zip(pts, pts[1:] + pts[:1])))
doc.recompute()
xz_members = [feature.make_profile("20-6", 1, 2, 100, doc, edge=(xz, "Edge1")),
              feature.make_profile("20-6", 2, 1, 100, doc, edge=(xz, "Edge2")),
              feature.make_profile("20-6", 1, 2, 100, doc, edge=(xz, "Edge3")),
              feature.make_profile("20-6", 2, 1, 100, doc, edge=(xz, "Edge4"))]
doc.recompute()
joints.create_joints(doc, xz_members, "Miter")
doc.recompute()
rows = cutlist.build_report(doc).pieces
check(len(rows) == 1 and rows[0][PIECE.index("Qty")] == 4 and rows[0][PIECE.index("Miter across (mm)")] == "40",
      f"1x2 and 2x1 mitered pieces share a row ({[(r[0], r[1], r[7]) for r in rows]})")

# [2] Closed faces are named on the upright section.
a = feature.make_profile("20-6", 1, 2, 300, doc, ClosedTop=True)     # narrow face closed
b = feature.make_profile("20-6", 2, 1, 300, doc, ClosedTop=True)     # wide face closed
c = feature.make_profile("20-6", 2, 1, 300, doc, ClosedRight=True)   # narrow face closed, on its side
doc.recompute()
check(feature.product_key(a) == feature.product_key(c) != feature.product_key(b),
      f"closed faces: {feature.product_key(a)} / {feature.product_key(b)} / {feature.product_key(c)}")
settings = pricing.get_settings(doc, create=True)
settings.ProfilePrices = {feature.legacy_product_key(b): "7"}
row = [r for r in cutlist.build_report(doc).pieces if b.Label in r[PIECE.index("Profiles")]][0]
check(row[PIECE.index("Price/m")] == 7.0, "price saved under the old key still applies")
for o in (a, b, c):
    doc.removeObject(o.Name)
doc.recompute()

# [1]/[7] A deleted sketch line under jointed profiles: the orphan is reported, not counted.
sk2 = doc.addObject("Sketcher::SketchObject", "Rect")
rp = [App.Vector(2000, 0, 0), App.Vector(2400, 0, 0), App.Vector(2400, 300, 0), App.Vector(2000, 300, 0)]
for p0, p1 in zip(rp, rp[1:] + rp[:1]):
    sk2.addGeometry(Part.LineSegment(p0, p1))
doc.recompute()
rect = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(sk2, f"Edge{i + 1}")) for i in range(4)]
doc.recompute()
joints.create_joints(doc, rect, "Butt", "Longest")
doc.recompute()
orphan = rect[1]
sk2.delGeometry(1)
doc.recompute()
cutlist.recompute_if_needed(doc)
report = cutlist.build_report(doc)
counted = " ".join(r[PIECE.index("Profiles")] for r in report.pieces)
check(orphan.Label not in counted and any(orphan.Label in e for e in report.errors),
      f"orphan profile reported, not counted ({report.errors})")
others = [p for p in rect if p is not orphan]
check(all(p.isValid() and "Touched" not in p.State for p in others), "the rest of the frame still computes")

# [12] ...and the Joints command skips it instead of failing for everything.
warnings = []
joints.create_joints(doc, [o for o in doc.Objects if feature.is_profile(o)], warnings=warnings)
check(any("skipped" in w and orphan.Label in w for w in warnings), "create_joints skips a broken profile")
for p in rect:
    doc.removeObject(p.Name)
for j in [o for o in doc.Objects if joints.is_joint(o) and not joints.ends_of(o)]:
    doc.removeObject(j.Name)
doc.recompute()

# An existing miter corner that gets a third profile becomes a butt joint.
_l, mring2 = ring_of("MiterPlus", 300, 300, "Miter", at=(8000, 0))
extra = lines_object("Upright", [((8000, 0, 0), (8000, 0, 250)), ((8000, 0, 250), (8000, 0, 0))])
doc.recompute()
up = feature.make_profile("20-6", 1, 1, 100, doc, edge=(extra, "Edge1"))
doc.recompute()
warnings = []
joints.create_joints(doc, [up], "Butt", "Vertical", warnings=warnings)
doc.recompute()
check(up.StartJoint is not None and up.StartJoint.Type == "Butt" and up.StartJoint.isValid()
      and any("from a miter to a butt joint" in w for w in warnings), f"miter corner plus upright -> butt ({warnings})")

# [3] Cancel/undo after a rename does not turn joints into manual ones.
doc.UndoMode = 1
_l, uring = ring_of("UndoRing", 400, 400, "Butt", at=(3000, 0))
before = {p.Name: round(p.Length.Value, 3) for p in uring}
rules_before = [j.ThroughRule for j in {p.StartJoint for p in uring}]
doc.openTransaction("rename")
uring[1].Label = "Renamed side"
uring[1].Rows = 2
doc.recompute()
doc.abortTransaction()
doc.recompute()
after = {p.Name: round(p.Length.Value, 3) for p in uring}
rules_after = [j.ThroughRule for j in {p.StartJoint for p in uring}]
check(after == before and "Manual" not in rules_after, f"abort keeps the joints automatic ({rules_after}, {after})")

# [4] Deleting the hand-picked profile sends the joint back to automatic, stably.
_l, sring = ring_of("StaleRing", 500, 300, "Butt", at=(4000, 0))
corner = sring[0].StartJoint
joints.swap(corner)
doc.recompute()
chosen = doc.getObject(corner.ThroughName)
doc.removeObject(chosen.Name)
doc.recompute()
first = (corner.ThroughRule, corner.ThroughName, corner.Through)
through, _e = joints.through_member(corner)
check(corner.ThroughRule != "Manual" and not corner.ThroughName and through is not None
      and corner.Through == through.Label, f"stale choice cleared ({first}, through {through and through.Label})")
corner.touch()
doc.recompute()
check((corner.ThroughRule, corner.ThroughName, corner.Through) == first, "and it stays that way")

# [6] Swap right after a rename, before any recompute.
_l, wring = ring_of("SwapRing", 400, 400, "Butt", at=(5000, 0))
corner = wring[0].StartJoint
target = [p for p, _e in joints.ends_of(corner)]
for p in target:
    p.Label = p.Label + " renamed"
try:
    joints.swap(corner)
    doc.recompute()
    check(corner.ThroughRule == "Manual" and doc.getObject(corner.ThroughName) in target, "swap after rename works")
except Exception as e:  # noqa: BLE001
    check(False, f"swap after rename raised {e!r}")

# [5]/[9] A new end that just misses an existing joint is reported.
_l, nring = ring_of("NearRing", 400, 400, "Butt", at=(6000, 0))
post = lines_object("Post", [((6000.5, 0, 0), (6000.5, 0, 300)), ((6000.5, 0, 300), (6000.5, 0, 0))])
doc.recompute()
pp = feature.make_profile("20-6", 1, 1, 100, doc, edge=(post, "Edge1"))
doc.recompute()
warnings = []
joints.create_joints(doc, [pp] + nring, warnings=warnings)
check(any("0.50 mm from" in w and "not added to that joint" in w for w in warnings),
      f"near miss with an existing joint reported ({warnings})")

# [10] A user's own description is left alone.
own = nring[0]
own.Label2 = "Mark holes before anodising"
cutlist.apply_marks(doc, cutlist.build_report(doc))
check(own.Label2 == "Mark holes before anodising", "user description kept")

# [14]/[15] Unknown or ambiguous materials: no guessed expansion, no thermal check.
cases = {"Glass-clear PETG": None, "Steel grey acrylic": None, "Aluminium-look acrylic": None,
         "Acrylic glass": 70.0, "Plexi glass": 70.0, "Organic glass": 70.0, "Clear glass": 9.0,
         "aluminum composite": 24.0}
got = {k: (panels.material_data(k) or (None, None))[1] for k in cases}
check(got == cases, f"ambiguous material names ({got})")
lines = lines_object("FitRing", [((7000, 0, 0), (7600, 0, 0)), ((7600, 0, 0), (7600, 400, 0)),
                                 ((7600, 400, 0), (7000, 400, 0)), ((7000, 400, 0), (7000, 0, 0))])
doc.recompute()
fring = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(lines, f"Edge{i + 1}")) for i in range(4)]
doc.recompute()
sheet = panels.make_panel(doc, fring, MaxTemperature=80)
doc.recompute()
check(panels.thermal_fit(sheet)[1] is not None, "hot acrylic too tight with the default insert")
sheet.Material = "Birch ply"
doc.recompute()
check(sheet.Expansion == 0 and panels.relative_change(sheet) == (0.0, 0.0) and panels.thermal_fit(sheet)[1] is None
      and abs(panels.thermal_fit(sheet)[0] - 0.1) < 1e-9 and "not recognised" in panels.panel_info(sheet),
      "unknown material: only the cut tolerance is checked, and the dialog says why")

# Currency and money format come from the system's region, not a fixed "€".
check(pricing.get_settings(doc, create=True).Currency == pricing.default_currency(),
      "default currency from the system region")
money = pricing.format_money(1234.56, "$")
check("$" in money and "234" in money and ("1,234.56" in money or "1.234,56" in money or "1 234,56" in money
                                          or "1 234,56" in money or "1 234,56" in money),
      f"money formatted by region ({money!r})")
from PySide import QtCore  # noqa: E402
us, india = QtCore.QLocale("en_US"), QtCore.QLocale("en_IN")
# Large totals keep their cents on Qt 5 too (its bindings pick integer or single-precision overloads).
check(pricing.money_in(us, 33554433.01, "$") == "$33,554,433.01" and pricing.money_in(us, -12.5, "$") == "-$12.50"
      and pricing.money_in(india, 1234567.89, "₹") == "₹12,34,567.89",
      # ascii(): a Windows console cannot print the rupee sign, and a failed print stops the script.
      f"exact money in any region ({pricing.money_in(us, 33554433.01, '$')}, "
      f"{ascii(pricing.money_in(india, 1234567.89, '₹'))})")

# [16] A shallow insert leaves room at the slot bottom.
sheet.Material = "Acrylic"
sheet.InsertDepth = 4.0  # 2.1 mm of the 6.1 mm slot unused
doc.recompute()
check(abs(panels.slot_room(sheet) - 2.6) < 1e-9 and panels.thermal_fit(sheet)[1] is None,
      f"slot room counts the unused depth ({panels.slot_room(sheet)})")

# ---- ties between rails at equal angles to the axes ------------------------------

import math  # noqa: E402

# A 400 mm square of 2020 turned 45° about Z: every corner joins a rail along (1, 1, 0) and
# one along (1, -1, 0), equally long and equally far from the axes. Which one runs through
# must follow the directions, not the order the profiles were made in (their names) or the
# way the lines were drawn, and each rail runs through at both of its ends or at neither.
turned = {}
for variant, numbers, flip in (("made forward", (1, 2, 3, 4), False),
                               ("made in reverse", (4, 3, 2, 1), False),
                               ("lines drawn backwards", (1, 2, 3, 4), True)):
    doc = App.newDocument("turned")
    r = 200 * math.sqrt(2)
    pts = [(r, 0, 0), (0, r, 0), (-r, 0, 0), (0, -r, 0)]
    lines = lines_object("TurnedSquare", [(b, a) if flip else (a, b) for a, b in zip(pts, pts[1:] + pts[:1])])
    doc.recompute()
    members = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(lines, f"Edge{i}")) for i in numbers]
    doc.recompute()
    joints.create_joints(doc, members, "Butt", "Longest")
    doc.recompute()
    through = {}
    for j in [o for o in doc.Objects if joints.is_joint(o)]:
        corner = tuple(round(c, 3) + 0.0 for c in j.Shape.Vertexes[0].Point)
        through[corner] = joints.through_member(j)[0].PathEdge[1][0]
    turned[variant] = through, sorted(round(p.Length.Value, 3) for p in members)
    App.closeDocument(doc.Name)
base, lengths = turned["made forward"]
check(len(base) == 4 and lengths == [380.0, 380.0, 420.0, 420.0],
      f"turned square: two rails run through at both ends ({lengths})")
for variant in ("made in reverse", "lines drawn backwards"):
    check(turned[variant][0] == base, f"turned square {variant}: same through member per corner "
                                      f"({turned[variant][0]}, made forward {base})")

print("\n%d failure(s)" % len(failures))

# A non-zero exit code lets CI see failures; os._exit skips FreeCAD's own exit handling.
sys.stdout.flush()
os._exit(1 if failures else 0)
