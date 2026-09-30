"""Panel fabrication, panel fit and stable piece marks. Run with:  freecadcmd tests/freecad_panels.py"""

import math
import os
import shutil
import sys
import tempfile

import freecad

ROOT = os.getcwd()
# Drop a copy of the workbench FreeCAD loaded at startup (see freecad_smoke.py).
for _name in [m for m in sys.modules if m == "freecad.profile_builder" or m.startswith("freecad.profile_builder.")]:
    del sys.modules[_name]
freecad.__path__.insert(0, os.path.join(ROOT, "freecad"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402
import Sketcher  # noqa: E402,F401

from freecad.profile_builder import cutlist, feature, joints, panels  # noqa: E402

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
doc = App.newDocument("pbpanels")


def lines_object(name, segments):
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = Part.makeCompound([Part.makeLine(V(*a), V(*b)) for a, b in segments])
    return obj


def frame(name, w, h, cols=1, rows=1):
    lines = lines_object(name, [((0, 0, 0), (w, 0, 0)), ((w, 0, 0), (w, h, 0)),
                                ((w, h, 0), (0, h, 0)), ((0, h, 0), (0, 0, 0))])
    doc.recompute()
    members = [feature.make_profile("20-6", cols, rows, 100, doc, edge=(lines, f"Edge{i + 1}")) for i in range(4)]
    doc.recompute()
    joints.create_joints(doc, members)
    doc.recompute()
    return members


def world_holes(panel):
    lay = panels.layout(panel)
    return [lay.to3d(u, v) for u, v in panels.drawing(panel, lay).holes]


# --- Holes on the slot centre lines -------------------------------------------------------------
ring = frame("Ring", 400, 300)
plain = panels.make_panel(doc, ring, Mount="On face", Thickness=3)
doc.recompute()
plain_mass = plain.Mass
check(plain.isValid() and plain.HoleCount == 0 and plain.CornerRadius.Value == 0, "no holes or rounding by default")

face = panels.make_panel(doc, ring, Mount="On face", Thickness=3, HoleDiameter=5.5, HoleSpacing=150,
                         EdgeDistance=8, CornerKeepout=25)
doc.recompute()
holes = world_holes(face)
check(face.isValid() and face.HoleCount == 14 == len(holes), f"14 holes around a 400 x 300 frame ({face.HoleCount})")
on_lines = all(min(abs(h.x), abs(h.x - 400)) < 1e-6 or min(abs(h.y), abs(h.y - 300)) < 1e-6 for h in holes)
check(on_lines, "every hole lies on a slot centre line (the profile centre lines of a 2020)")
corners = [V(x, y, 0) for x in (0, 400) for y in (0, 300)]
check(all(min(math.hypot(h.x - c.x, h.y - c.y) for c in corners) >= 25 - 1e-6 for h in holes),
      "no hole within the keep-out of a joint")
bottom = sorted(h.x for h in holes if abs(h.y) < 1e-6)
check(len(bottom) == 4 and max(b - a for a, b in zip(bottom, bottom[1:])) <= 150 + 1e-6,
      f"evenly spaced, at most 150 mm apart ({[round(x, 1) for x in bottom]})")
top = max(h.z for h in holes)
check(abs(top - face.Shape.BoundBox.ZMin) < 1e-6 or abs(top - face.Shape.BoundBox.ZMax) < 1e-6,
      "holes are drawn on the sheet surface")
removed = face.HoleCount * math.pi * 2.75 ** 2 * 3 * face.Density * 1e-6
check(abs(plain_mass - face.Mass - removed) < 2e-4, f"holes are cut out of the solid ({plain_mass - face.Mass:.4f} kg)")
check(len(face.Shape.Solids) == 1 and face.Shape.isValid(), "the sheet stays one valid solid")

face.EdgeDistance = 12
doc.recompute()
d = panels.drawing(face)
check(face.HoleCount == 0 and any("closer than the edge distance" in n for n in d.notes),
      f"slot lines too close to the edge are reported, not dropped silently ({d.notes[:1]})")
face.EdgeDistance = 8
doc.recompute()

# A 2040 lying flat has two slots under the sheet.
flat_ring = None
for cols, rows in ((2, 1), (1, 2)):
    members = frame(f"Flat{cols}{rows}", 400, 300, cols, rows)
    test = panels.make_panel(doc, members, Mount="On face", HoleDiameter=5, SlotChoice="All")
    doc.recompute()
    if len(panels.slot_lines(test, panels.layout(test))[0]) == 8:
        flat_ring, flat = members, test
        break
check(flat_ring is not None, "a flat 2040 frame offers two slot lines per member")
if flat_ring is not None:
    def edge_gap(panel):
        lay = panels.layout(panel)
        us = [u for u, _v in lay.corners]
        vs = [v for _u, v in lay.corners]
        gaps = set()
        for name, p, q in panels.slot_lines(panel, lay)[0]:
            if abs(p[1] - q[1]) < 1e-6:  # along e1: distance to the nearer long edge
                gaps.add(round(min(p[1] - min(vs), max(vs) - p[1]), 3))
            else:
                gaps.add(round(min(p[0] - min(us), max(us) - p[0]), 3))
        return gaps
    check(edge_gap(flat) == {10.0, 30.0}, f"All: both slots ({edge_gap(flat)})")
    flat.SlotChoice = "Outer"
    doc.recompute()
    check(edge_gap(flat) == {10.0}, f"Outer: the slot 10 mm from the sheet edge ({edge_gap(flat)})")
    flat.SlotChoice = "Inner"
    doc.recompute()
    check(edge_gap(flat) == {30.0}, f"Inner: the slot 30 mm from the sheet edge ({edge_gap(flat)})")

# --- Rounded corners and cutouts ----------------------------------------------------------------
rounded = panels.make_panel(doc, ring, Mount="On face", Thickness=3, CornerRadius=10)
doc.recompute()
corner_loss = 4 * (100 - math.pi * 25) * 3 * rounded.Density * 1e-6
check(rounded.isValid() and abs(plain_mass - rounded.Mass - corner_loss) < 1e-4,
      f"rounded corners ({(plain_mass - rounded.Mass) * 1000:.2f} g removed)")
check(len([e for e in rounded.Shape.Edges if e.Curve.TypeId == "Part::GeomCircle"]) == 8, "four arcs on each face")

sk = doc.addObject("Sketcher::SketchObject", "Fan")
sk.Placement = App.Placement(V(0, 0, 7), App.Rotation())
sk.addGeometry(Part.Circle(V(200, 150, 0), V(0, 0, 1), 30))
for a, b in (((60, 60), (120, 60)), ((120, 60), (120, 90)), ((120, 90), (60, 90)), ((60, 90), (60, 60))):
    sk.addGeometry(Part.LineSegment(V(*a, 0), V(*b, 0)))
doc.recompute()
cut = panels.make_panel(doc, ring, cutouts=sk, Mount="On face", Thickness=3)
doc.recompute()
cut_loss = (math.pi * 900 + 60 * 30) * 3 * cut.Density * 1e-6
check(cut.isValid() and abs(plain_mass - cut.Mass - cut_loss) < 1e-4,
      f"sketch cutouts go through the sheet ({(plain_mass - cut.Mass) * 1000:.2f} g removed)")
d = panels.drawing(cut)
check(sorted(len(loop) for loop in d.cutouts) == [1, 4] and d.cutouts[0][0][0] in ("circle", "line"),
      "cutouts are in the flat drawing too")
tilted = doc.addObject("Sketcher::SketchObject", "Tilted")
tilted.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 30))
tilted.addGeometry(Part.Circle(V(200, 150, 0), V(0, 0, 1), 20))
doc.recompute()
bad = panels.make_panel(doc, ring, cutouts=tilted, Mount="On face")
doc.recompute()
check(not bad.isValid() and "parallel" in bad.getStatusString(), f"a tilted cutout sketch is refused ({bad.getStatusString()})")
report = cutlist.build_report(doc)
check(any(bad.Label in e for e in report.errors), "and the cut list says so")
doc.removeObject(bad.Name)
doc.recompute()

# --- The cut list: marks, holes, identical sheets -----------------------------------------------
back = panels.make_panel(doc, ring, Mount="On face", Side="Back", Thickness=3, HoleDiameter=5.5,
                         HoleSpacing=150, EdgeDistance=8, CornerKeepout=25)
doc.recompute()
report = cutlist.build_report(doc)
SHEET = cutlist.SHEET_HEADER
rows = {r[SHEET.index("Holes")]: r for r in report.sheets}
row = rows.get("14 × Ø5.5")
check(row is not None and row[SHEET.index("Qty")] == 2, f"front and back sheet are the same part, flipped ({rows.keys()})")
# plain, front + back, the flat 2040 frame, rounded, cutouts
check(len(report.sheets) == 5 and all(r[0].startswith("P-") for r in report.sheets),
      f"sheets get marks P-1... ({[r[0] for r in report.sheets]})")
check(report.marks[face.Name] == report.marks[back.Name] != report.marks[plain.Name], "marks follow the part")
hardware = [h for h in report.hardware if "sheet holes" in h[1]]
check(hardware and hardware[0][0] == 28, f"screws for the holes in the hardware list ({hardware})")

# --- Export -----------------------------------------------------------------------------------
out = tempfile.mkdtemp(prefix="pb_panels_")
try:
    written = panels.export_panels(doc, out, report.marks, unit=("mm", 1.0))
    names = sorted(os.path.basename(p) for p in written)
    check(len(written) == 10 and all(os.path.exists(p) for p in written), f"one DXF and SVG per part ({names})")
    holed = [p for p in written if os.path.basename(p).startswith(report.marks[face.Name] + "_")
             and p.endswith(".dxf")]
    text = open(holed[0], encoding="ascii").read() if holed else ""
    entities = text.split("\n")
    check(entities.count("CIRCLE") == 14 and "Acrylic_3_mm_420x320mm" in holed[0],
          f"the DXF has the holes and a file name with size and unit ({os.path.basename(holed[0]) if holed else ''})")
    inch = panels.export_panels(doc, out, {cut.Name: "P-9"}, unit=("in", 1 / 25.4))
    text = open(inch[0], encoding="ascii").read()
    check(inch[0].endswith("16.54x12.60in.dxf") and "16.535433" in text and "in  " not in text[:20],
          f"inch export ({os.path.basename(inch[0])})")
    svg = open(inch[1], encoding="utf-8").read()
    check('in" height=' in svg and svg.count("<circle") == 1, "SVG at true size in inches, with the round cutout")
finally:
    shutil.rmtree(out, ignore_errors=True)

# --- Fit checks ---------------------------------------------------------------------------------
face.ScrewDiameter = 5
face.MaxTemperature = 80
doc.recompute()
need, play, warning = panels.hole_play(face)
check(warning is not None and abs(play - 0.25) < 1e-9 and need > 0.5, f"hot acrylic needs more hole play ({need:.2f} mm)")
check("Ø" in warning and any(w == warning for w in cutlist.build_report(doc).warnings), "the report says which drill")
face.HoleDiameter = 7.5
doc.recompute()
check(panels.hole_play(face)[2] is None and face.HoleCount == 14, "bigger holes fit")

slot = panels.make_panel(doc, ring, Thickness=3, HoleDiameter=5, CutTolerance=0.2)
doc.recompute()
d = panels.drawing(slot)
check(slot.HoleCount == 0 and any("only placed on panels mounted on the face" in n for n in d.notes),
      "in-slot panels get no holes, and say so")
check(any("slide each one in" in w for w in cutlist.build_report(doc).warnings), "the report says to slide the sheet in")
check(panels.cold_fit(slot) is None, "a normal in-slot sheet stays in its slots when cold")
slot.MinTemperature = -40
slot.Clearance = 2
doc.recompute()
cold = panels.cold_fit(slot)
check(cold is not None and "lips" in cold and "can come out" in cold, f"too much clearance: the sheet can come out ({cold})")
check("Too loose when cold" in panels.panel_info(slot), "the dialog says so")
glass = panels.make_panel(doc, ring, Thickness=3, Material="Glass", MinTemperature=20, MaxTemperature=80)
doc.recompute()
check(panels.relative_change(glass)[0] == 0 and panels.relative_change(glass)[1] > 0,
      "glass shrinks against the frame when hot")

# --- Stable piece marks -------------------------------------------------------------------------
mdoc = App.newDocument("pbmarks")
bars = [feature.make_profile("20-6", 1, 1, length, mdoc) for length in (500, 500, 400, 300)]
mdoc.recompute()
report = cutlist.build_report(mdoc)
cutlist.apply_marks(mdoc, report)
first = {p.Name: p.PieceMark for p in bars}
check([first[p.Name] for p in bars] == ["A1", "A1", "A2", "A3"], f"first marks, longest first ({first})")
store = cutlist.mark_store(mdoc)
check(store is not None and "Touched" not in store.State and all("Touched" not in p.State for p in bars),
      "marks are stored without touching anything")
bars[2].Length = 450  # A2 changes; A1 and A3 stay
mdoc.recompute()
report = cutlist.build_report(mdoc)
cutlist.apply_marks(mdoc, report)
check([p.PieceMark for p in bars] == ["A1", "A1", "A4", "A3"], f"other marks stay put ({[p.PieceMark for p in bars]})")
extra = feature.make_profile("20-6", 1, 2, 800, mdoc)
mdoc.recompute()
report = cutlist.build_report(mdoc)
cutlist.apply_marks(mdoc, report)
check(extra.PieceMark == "B1" and bars[0].PieceMark == "A1", "a new product gets the next letter")
check([r[0] for r in report.pieces] == ["A1", "A3", "A4", "B1"], f"rows in mark order ({[r[0] for r in report.pieces]})")
path = os.path.join(tempfile.gettempdir(), "pb_marks.FCStd")
names = [b.Name for b in bars]
mdoc.saveAs(path)
App.closeDocument(mdoc.Name)
mdoc = App.openDocument(path)
p = mdoc.getObject(names[3])
p.Length = 350
mdoc.recompute()
report = cutlist.build_report(mdoc)
check(report.marks[p.Name] == "A5", f"marks survive saving: the next number is A5 ({report.marks[p.Name]})")
cutlist.renumber_marks(mdoc)
report = cutlist.build_report(mdoc)
check(sorted(set(report.marks.values())) == ["A1", "A2", "A3", "B1"], f"renumbering closes the gaps ({report.marks})")
App.closeDocument(mdoc.Name)
os.remove(path)

# Older documents: panels open unchanged.
for fixture in ("legacy_8733122.FCStd", "legacy_ead3f7d.FCStd"):
    old = App.openDocument(os.path.join(ROOT, "tests", "fixtures", fixture))
    found = [o for o in old.Objects if panels.is_panel(o)]
    check(all(o.HoleDiameter.Value == 0 and o.CornerRadius.Value == 0 and o.CutTolerance.Value == 0
              and o.Cutouts is None for o in found), f"{fixture}: {len(found)} panel(s) open without holes or tolerance")
    App.closeDocument(old.Name)

print(f"\n{len(failures)} failure(s)")
for f in failures:
    print("  " + f)
