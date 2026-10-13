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

from freecad.profile_builder import cutlist, fabrication, feature, joints, panels  # noqa: E402

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
check("Too loose at -40 °C" in panels.panel_info(slot), "the dialog says so, and names the temperature")
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

# --- Review fixes -------------------------------------------------------------------------------
rdoc = App.newDocument("pbreview")
doc = rdoc  # lines_object() and frame() use it
ring = frame("R", 400, 300)
fans = []
for r in (20, 40):
    fan = rdoc.addObject("Sketcher::SketchObject", f"Fan{r}")
    fan.addGeometry(Part.Circle(V(200, 150, 0), V(0, 0, 1), r))
    fans.append(fan)
rdoc.recompute()
small, large = (panels.make_panel(rdoc, ring, cutouts=f, Mount="On face") for f in fans)
plain_slot = panels.make_panel(rdoc, ring)
holed_slot = panels.make_panel(rdoc, ring, HoleDiameter=5)
rdoc.recompute()
report = cutlist.build_report(rdoc)
check(report.marks[small.Name] != report.marks[large.Name], "fan holes of different sizes are different sheets")
check(report.marks[plain_slot.Name] == report.marks[holed_slot.Name],
      "a hole diameter without holes does not make another sheet")

acrylic = panels.make_panel(rdoc, ring, Mount="On face", HoleDiameter=5.5, ScrewDiameter=5, MaxTemperature=42)
rdoc.recompute()
warning = panels.hole_play(acrylic)[2] or ""
drill = float(warning.rsplit("Ø", 1)[1]) if "drill at least" in warning else 0
acrylic.HoleDiameter = drill
rdoc.recompute()
check(drill and panels.hole_play(acrylic)[2] is None, f"drilling the advised Ø{drill} passes the check")
acrylic.HoleDiameter = 0
rdoc.recompute()
check("set HoleDiameter and ScrewDiameter" in panels.panel_info(acrylic), "without holes the dialog asks for both")

unknown = panels.make_panel(rdoc, ring, Material="PVC foam")
rdoc.recompute()
info = panels.panel_info(unknown)
check("thermal fit not checked" in info and "°C)" not in info, f"unknown material: no temperatures claimed ({info})")

big = frame("Big", 1220, 800)
hot = panels.make_panel(rdoc, big, MinTemperature=0, MaxTemperature=70)
rdoc.recompute()
found = panels.fit_warnings(hot)
check(len(found) == 1 and "no Clearance or InsertDepth" in found[0], f"an impossible fit says so once ({found})")
check("raise Clearance" not in panels.panel_info(hot) and "lower Clearance" not in panels.panel_info(hot),
      "and gives no advice that brings back the other warning")
glass = panels.make_panel(rdoc, big, Material="Glass", MinTemperature=20, MaxTemperature=80, Clearance=2)
rdoc.recompute()
check("Too loose at 80 °C" in panels.panel_info(glass), "glass is loosest when hot")

out = tempfile.mkdtemp(prefix="pb_review_")
try:
    onface = panels.make_panel(rdoc, frame("F40", 500, 400, 1, 1), Mount="On face", HoleDiameter=5.5,
                               Material="Acrylglas weiß")
    rdoc.recompute()
    written = panels.export_panels(rdoc, out, {onface.Name: "P-7"}, unit=("mm", 1.0))
    check("weiß" in os.path.basename(written[0]), f"file names keep the material ({os.path.basename(written[0])})")
    lines = open(written[0], encoding="ascii").read().split("\n")
    i = lines.index("TEXT")
    text_y = float(lines[i + 6])
    d = panels.drawing(onface)
    ymin = fabrication.bounds(d.segments)[1]
    low = [v - ymin for _u, v in d.holes if v - ymin < 30]
    check(all(text_y > h + d.diameter / 2 for h in low), f"the label sits above the lower holes ({text_y}, {low[:2]})")
    check("weiss" in lines[i + 12], f"DXF text spells out ß ({lines[i + 12]})")
finally:
    shutil.rmtree(out, ignore_errors=True)

# An L-shaped sheet gets holes on every side, all on the sheet.
lshape = lines_object("LShape", [((0, 0, 0), (400, 0, 0)), ((400, 0, 0), (400, 200, 0)), ((400, 200, 0), (200, 200, 0)),
                                 ((200, 200, 0), (200, 400, 0)), ((200, 400, 0), (0, 400, 0)), ((0, 400, 0), (0, 0, 0))])
rdoc.recompute()
lmembers = [feature.make_profile("20-6", 1, 1, 100, rdoc, edge=(lshape, f"Edge{i + 1}")) for i in range(6)]
rdoc.recompute()
joints.create_joints(rdoc, lmembers)
lpanel = panels.make_panel(rdoc, lmembers, Mount="On face", HoleDiameter=5)
rdoc.recompute()
d = panels.drawing(lpanel)
outline = fabrication.polygon_of(d.segments)
on_side = {m.Label for m in lmembers for h in world_holes(lpanel)
           if feature.path_edge(m).distToShape(Part.Vertex(V(h.x, h.y, 0)))[0] < 1e-6}
check(len(on_side) == 6 and all(fabrication.inside(h, outline) for h in d.holes) and not d.notes,
      f"an L-shaped sheet has holes on all six sides ({len(on_side)}, {d.notes})")

# Rounded corners: no hole off the sheet or too close to its edge.
round80 = panels.make_panel(rdoc, ring, Mount="On face", HoleDiameter=5, CornerRadius=80)
rdoc.recompute()
d = panels.drawing(round80)
outline = fabrication.polygon_of(d.segments)
check(d.holes and all(fabrication.inside(h, outline) and fabrication._to_polygon(h, outline) >= 7.9 for h in d.holes),
      f"holes stay on a sheet with large rounded corners ({len(d.holes)})")

# A mitered frame of flat 2080: the inner slots end at the miter, so no hole lands on solid metal.
for cols, rows in ((4, 1), (1, 4)):
    # Away from the other test frames, so its corners do not join theirs.
    y = 5000 + 1000 * cols
    wide = lines_object(f"Wide{cols}", [((0, y, 0), (800, y, 0)), ((800, y, 0), (800, y + 600, 0)),
                                        ((800, y + 600, 0), (0, y + 600, 0)), ((0, y + 600, 0), (0, y, 0))])
    rdoc.recompute()
    wmembers = [feature.make_profile("20-6", cols, rows, 100, rdoc, edge=(wide, f"Edge{i + 1}")) for i in range(4)]
    rdoc.recompute()
    joints.create_joints(rdoc, wmembers, joint_type="Miter")
    wpanel = panels.make_panel(rdoc, wmembers, Mount="On face", HoleDiameter=5, SlotChoice="All", CornerKeepout=10)
    rdoc.recompute()
    if len(panels.slot_lines(wpanel, panels.layout(wpanel))[0]) == 16:
        lay = panels.layout(wpanel)
        down = -lay.n if lay.lift > 0 else lay.n
        solid = [h for h in world_holes(wpanel) if any(m.Shape.isInside(h + down * 1.0, 1e-6, True) for m in wmembers)]
        check(wpanel.HoleCount > 0 and not solid, f"mitered flat 2080: no holes over solid metal ({len(solid)})")
        break

# Profiles anchored off the sketch plane still keep holes away from their joints.
aring = frame("Anchored", 400, 300)
for m in aring:
    m.Anchor = "Bottom center" if "Bottom center" in m.getEnumerationsOfProperty("Anchor") else m.Anchor
rdoc.recompute()
apanel = panels.make_panel(rdoc, aring, Mount="On face", HoleDiameter=5)
rdoc.recompute()
points = panels._joint_points(apanel, panels.layout(apanel))
check(len(points) == 4, f"the frame's four joints are keep-outs ({len(points)})")

# A cutout sketch inside a Body with its own placement is cut where it shows.
body = rdoc.addObject("PartDesign::Body", "Body")
body.Placement = App.Placement(V(100, 0, 0), App.Rotation())
bsk = body.newObject("Sketcher::SketchObject", "BodyFan")
bsk.addGeometry(Part.Circle(V(150, 150, 0), V(0, 0, 1), 20))
rdoc.recompute()
bpanel = panels.make_panel(rdoc, ring, cutouts=bsk, Mount="On face")
rdoc.recompute()
mid = (bpanel.Shape.BoundBox.ZMin + bpanel.Shape.BoundBox.ZMax) / 2
check(bpanel.isValid() and not bpanel.Shape.isInside(V(250, 150, mid), 1e-6, True)
      and bpanel.Shape.isInside(V(150, 150, mid), 1e-6, True), "a Body's sketch is cut at its real place")
check(rdoc.getObject(bpanel.Name).getTypeIdOfProperty("Cutouts") == "App::PropertyLinkGlobal", "a global link")

empty = rdoc.addObject("Sketcher::SketchObject", "Empty")
rdoc.recompute()
epanel = panels.make_panel(rdoc, ring, cutouts=empty, Mount="On face")
rdoc.recompute()
check(epanel.isValid(), f"an empty cutout sketch is fine ({epanel.getStatusString()})")
cover = rdoc.addObject("Sketcher::SketchObject", "Cover")
for a, b in (((-50, -50), (450, -50)), ((450, -50), (450, 350)), ((450, 350), (-50, 350)), ((-50, 350), (-50, -50))):
    cover.addGeometry(Part.LineSegment(V(*a, 0), V(*b, 0)))
rdoc.recompute()
cpanel = panels.make_panel(rdoc, ring, cutouts=cover, Mount="On face")
rdoc.recompute()
check(not cpanel.isValid() and "whole sheet" in cpanel.getStatusString(), "a cutout over the whole sheet is an error")
rdoc.removeObject(cpanel.Name)

notch = rdoc.addObject("Sketcher::SketchObject", "Notch")
notch.addGeometry(Part.Circle(V(260, 0, 0), V(0, 0, 1), 15))
rdoc.recompute()
npanel = panels.make_panel(rdoc, ring, cutouts=notch, Mount="On face", HoleDiameter=5, HoleSpacing=40)
rdoc.recompute()
d = panels.drawing(npanel)
check(all(math.hypot(u - 260, v) > 15 + 2.5 for u, v in [(p.x, p.y) for p in world_holes(npanel)])
      and any("cut into a cutout" in n for n in d.notes), "holes that would cut into a cutout are left out")
rdoc.recompute()

# Undo past a cut list must not hand a printed mark to another piece.
mdoc = App.newDocument("pbundo")
mdoc.UndoMode = 1
pieces_ = [feature.make_profile("20-6", 1, 1, length, mdoc) for length in (500, 400)]
mdoc.recompute()
cutlist.apply_marks(mdoc, cutlist.build_report(mdoc))
mdoc.openTransaction("edit")
pieces_[1].Length = 450
mdoc.commitTransaction()
mdoc.recompute()
mdoc.openTransaction("cut list")
cutlist.apply_marks(mdoc, cutlist.build_report(mdoc))
mdoc.commitTransaction()
printed = pieces_[1].PieceMark
mdoc.undo()
mdoc.undo()
mdoc.recompute()
pieces_[1].Length = 350
mdoc.recompute()
again = cutlist.build_report(mdoc).marks[pieces_[1].Name]
check(printed == "A3" and again == "A4", f"after undo the 350 mm piece gets a new mark ({printed} then {again})")
App.closeDocument(mdoc.Name)

# Undoing the very first cut list removes the Piece marks object; the marks it gave still count.
mdoc = App.newDocument("pbundo2")
mdoc.UndoMode = 1
pieces_ = [feature.make_profile("20-6", 1, 1, length, mdoc) for length in (500, 400)]
mdoc.recompute()
mdoc.openTransaction("cut list")
cutlist.apply_marks(mdoc, cutlist.build_report(mdoc))
mdoc.commitTransaction()
mdoc.undo()
gone = cutlist.mark_store(mdoc) is None
pieces_[1].Length = 450
mdoc.recompute()
again = cutlist.build_report(mdoc).marks[pieces_[1].Name]
check(gone and again == "A3", f"after undoing the first cut list the 450 mm piece gets A3, not A2 ({gone}, {again})")
App.closeDocument(mdoc.Name)
App.closeDocument(rdoc.Name)

# Members need not be centred on one plane: a section offset (Align slots) or a different section size moves
# a centre line, as long as one plane reaches every member. The result must not depend on the order of Profiles.
def rotations(members):
    return [members[i:] + members[:i] for i in range(len(members))]


def sheet_span(panel, members, axis, **props):
    """(the sheet's range along a world axis, its largest overlap with a member) for this order, or the error."""
    panel.Profiles = members
    for name, value in props.items():
        setattr(panel, name, value)
    try:
        panels.layout(panel)
    except ValueError as error:
        return str(error)
    panel.Document.recompute()
    bb = panel.Shape.BoundBox
    overlap = max(panel.Shape.common(m.Shape).Volume for m in members)
    return (round(getattr(bb, axis + "Min"), 3), round(getattr(bb, axis + "Max"), 3)), round(overlap, 1)


def ring(name, sizes, anchor="Center", join=True):
    lines = lines_object(name, [((0, 0, 0), (400, 0, 0)), ((400, 0, 0), (400, 300, 0)),
                                ((400, 300, 0), (0, 300, 0)), ((0, 300, 0), (0, 0, 0))])
    doc.recompute()
    members = [feature.make_profile("20-6", c, r, 100, doc, edge=(lines, f"Edge{i + 1}"), Anchor=anchor)
               for i, (c, r) in enumerate(sizes)]
    doc.recompute()
    if join:
        joints.create_joints(doc, members)
        doc.recompute()
    return members


doc = App.newDocument("pbwall")  # lines_object() uses the global doc
wall = lines_object("Wall", [((0, 0, 0), (400, 0, 0)), ((400, 0, 0), (400, 0, 300)),
                             ((400, 0, 300), (0, 0, 300)), ((0, 0, 300), (0, 0, 0))])
doc.recompute()
bottom = feature.make_profile("20-6", 1, 3, 100, doc, edge=(wall, "Edge1"))
right_post = feature.make_profile("20-6", 2, 2, 100, doc, edge=(wall, "Edge2"))
top = feature.make_profile("20-6", 2, 1, 100, doc, edge=(wall, "Edge3"))
left_post = feature.make_profile("20-6", 2, 2, 100, doc, edge=(wall, "Edge4"))
wall_members = [bottom, right_post, top, left_post]
for member, label in zip(wall_members, ("bottom rail", "right post", "top rail", "left post")):
    member.Label = label
    feature.ensure_section_offset_properties(member)
bottom.SectionOffsetX = -10
doc.recompute()
shifted = feature.member_frame(bottom).center_offset()
check(abs(shifted.y + 10) < 1e-7, f"the bottom rail's section centre is 10 mm off its sketch edge ({shifted})")
wall_panel = panels.make_panel(doc, wall_members, Mount="In slot", Thickness=3)
doc.recompute()
spans = [sheet_span(wall_panel, order, "Y") for order in rotations(wall_members)]
check(all(s == ((-11.5, -8.5), 0.0) for s in spans),
      f"an In slot sheet sits in the bottom rail's slot plane, 10 mm off the posts' centre lines, "
      f"whatever the order of Profiles ({spans})")
sheet_span(wall_panel, wall_members, "Y")
lip = bottom.SlotDepth.Value - wall_panel.Clearance.Value
bb = wall_panel.Shape.BoundBox
check(abs(bb.XMin - (20 - lip)) < 1e-6 and abs(bb.XMax - (380 + lip)) < 1e-6
      and abs(bb.ZMin - (30 - lip)) < 1e-6 and abs(bb.ZMax - (290 + lip)) < 1e-6,
      f"its edges sit {lip:g} mm deep in every slot (X {bb.XMin:.2f}..{bb.XMax:.2f}, Z {bb.ZMin:.2f}..{bb.ZMax:.2f})")

bottom.SectionOffsetX = 10
doc.recompute()
spans = [sheet_span(wall_panel, order, "Y") for order in rotations(wall_members)]
check(all(s == ((8.5, 11.5), 0.0) for s in spans), f"and with the rail offset the other way ({spans})")

# The plane misses the posts' slots first, and the post's own nearest slot (PlaneOffset -20) misses the
# rail's only slot: the suggestion must suit every member.
order = [right_post, top, left_post, bottom]
message = sheet_span(wall_panel, order, "Y", PlaneOffset=-12)
check(isinstance(message, str) and "misses the slots of right post; try PlaneOffset +0 mm" in message,
      f"the suggested PlaneOffset suits every member, not just the one missed ({message})")
check(sheet_span(wall_panel, order, "Y", PlaneOffset=0) == ((8.5, 11.5), 0.0), "and it puts the sheet in every slot")
top.SectionOffsetX = 5
doc.recompute()
message = sheet_span(wall_panel, order, "Y")
check(isinstance(message, str) and "no PlaneOffset passes through a slot of every profile" in message,
      f"slots that no plane passes through all at once are reported as such ({message})")
top.SectionOffsetX = 0

bottom.SectionOffsetX = -100
doc.recompute()
errors = [sheet_span(wall_panel, order, "Y", PlaneOffset=0) for order in rotations(wall_members)]
check(all(isinstance(e, str) and e.startswith("bottom rail does not lie in the plane") for e in errors),
      f"a member far from the others is the one rejected, whatever the order ({errors})")
App.closeDocument(doc.Name)

# On face: the sheet lies on the outermost face of all members, not on the first member's.
doc = App.newDocument("pbonface")
rails = ring("Ring", [(1, 1)] * 4)
raised = rails[2]
feature.ensure_section_offset_properties(raised)
raised.SectionOffsetY = 10
doc.recompute()
check(abs(raised.Shape.BoundBox.ZMax - 20) < 1e-6, f"a raised rail reaches Z 20 ({raised.Shape.BoundBox.ZMax:g})")
face_panel = panels.make_panel(doc, rails, Mount="On face", Thickness=3)
doc.recompute()
for side, expected in (("Front", (20.0, 23.0)), ("Back", (-13.0, -10.0))):
    spans = [sheet_span(face_panel, order, "Z", Side=side) for order in rotations(rails)]
    check(all(s == (expected, 0.0) for s in spans),
          f"an On face {side} sheet lies on the raised rail and clears every member, raised rail first or not "
          f"({spans})")
App.closeDocument(doc.Name)

# Mixed sizes flush on one face (Bottom center anchor): 2020 rails and 4040 posts.
doc = App.newDocument("pbflush")
mixed = ring("Ring", [(1, 1), (2, 2), (1, 1), (2, 2)], anchor="Bottom center")
mixed_panel = panels.make_panel(doc, mixed, Mount="On face", Thickness=3)
doc.recompute()
for side, expected in (("Front", (40.0, 43.0)), ("Back", (-3.0, 0.0))):
    spans = [sheet_span(mixed_panel, order, "Z", Side=side) for order in rotations(mixed)]
    check(all(s == (expected, 0.0) for s in spans),
          f"an On face {side} sheet on 2020 rails and 4040 posts lies on the posts, whatever the order ({spans})")
slot_panel = panels.make_panel(doc, mixed, Mount="In slot", Thickness=3)
doc.recompute()
spans = [sheet_span(slot_panel, order, "Z") for order in rotations(mixed)]
check(all(s == ((8.5, 11.5), 0.0) for s in spans),
      f"an In slot sheet uses the slots the rails and posts share, whatever the order ({spans})")
App.closeDocument(doc.Name)

# 2x4 posts with 1x1 rails lined up with the posts' outer slot (Align slots).
doc = App.newDocument("pbouter")
tall = ring("Ring", [(1, 1), (2, 4), (1, 1), (2, 4)], join=False)
for rail in (tall[0], tall[2]):
    feature.ensure_section_offset_properties(rail)
    rail.SectionOffsetY = 30
doc.recompute()
outer_panel = panels.make_panel(doc, tall, Mount="In slot", Thickness=3)
doc.recompute()
spans = [sheet_span(outer_panel, order, "Z") for order in rotations(tall)]
check(all(s == ((28.5, 31.5), 0.0) for s in spans),
      f"a sheet in the posts' outer slot is accepted with a post first or a rail first ({spans})")
App.closeDocument(doc.Name)

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

# A non-zero exit code lets CI see failures; os._exit skips FreeCAD's own exit handling.
sys.stdout.flush()
os._exit(1 if failures else 0)
