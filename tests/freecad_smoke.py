"""Headless feature test. Run with:  freecadcmd tests/freecad_smoke.py"""

import os
import tempfile

import freecad

ROOT = os.getcwd()
freecad.__path__.append(os.path.join(ROOT, "freecad"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402
import Sketcher  # noqa: E402

from freecad.profile_builder import cutlist, feature, joints, panels, pricing  # noqa: E402

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
pieces = sum(r[0] for r in report.pieces)
check(pieces == 5, f"cut list pieces {pieces}")
sheet = cutlist.write_spreadsheet(doc, report)
check(sheet.getContents("A2") in ("Qty", "'Qty"), f"spreadsheet header {sheet.getContents('A2')!r}")
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
created = joints.create_joints(doc, cube, "Butt", "Vertical")
doc.recompute()
check(len(created) == 8, f"cube: 8 corner joints ({len(created)})")
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
segments = [((a[0] * 1.5, a[1], a[2]), (b[0] * 1.5, b[1], b[2])) for a, b in segments]
lines.Shape = Part.makeCompound([Part.makeLine(App.Vector(*a), App.Vector(*b)) for a, b in segments])
doc.recompute()
x_rails = sorted(round(p.Length.Value, 3) for p in cube if abs(feature.member_frame(p).z.x) > 0.9)
check(x_rails == [570.0] * 4, f"cube: stretched X rails 570 ({x_rails})")

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

print("\n%d failure(s)" % len(failures))
