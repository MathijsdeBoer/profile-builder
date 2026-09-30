"""Frame check. Run with:  freecadcmd tests/freecad_check.py"""

import os
import sys
import time

import freecad

ROOT = os.getcwd()
# Drop a copy of the workbench FreeCAD loaded at startup (see freecad_smoke.py).
for _name in [m for m in sys.modules if m == "freecad.profile_builder" or m.startswith("freecad.profile_builder.")]:
    del sys.modules[_name]
freecad.__path__.insert(0, os.path.join(ROOT, "freecad"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402

from freecad.profile_builder import check, feature, joints, panels, pricing  # noqa: E402

_loaded = os.path.normcase(os.path.realpath(feature.__file__))
if not _loaded.startswith(os.path.normcase(os.path.realpath(ROOT))):
    raise SystemExit(f"testing the wrong copy of the workbench: {_loaded} is not under {ROOT}")
print(f"testing {os.path.dirname(_loaded)}")

failures = []


def check_(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


V = App.Vector


def lines_object(doc, name, segments):
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = Part.makeCompound([Part.makeLine(V(*a), V(*b)) for a, b in segments])
    doc.recompute()
    return obj


def on_edges(doc, lines, count=None, size=(1, 1)):
    n = count or len(lines.Shape.Edges)
    made = [feature.make_profile("20-6", size[0], size[1], 100, doc, edge=(lines, f"Edge{i + 1}")) for i in range(n)]
    doc.recompute()
    return made


def problems(found):
    return [f for f in found if f.severity != "Info"]


# --- A clean cube: nothing to report but its size -----------------------------------------------
doc = App.newDocument("pbcheck")
S = 400
corners = [(0, 0), (S, 0), (S, S), (0, S)]
segments = []
for z in (0, S):
    segments += [((*a, z), (*b, z)) for a, b in zip(corners, corners[1:] + corners[:1])]
segments += [((x, y, 0), (x, y, S)) for x, y in corners]
cube_lines = lines_object(doc, "Cube", segments)
cube = on_edges(doc, cube_lines)
joints.create_joints(doc, cube)
doc.recompute()
start = time.time()
found = check.run(doc)
took = time.time() - start
check_(not problems(found), f"a joined cube has no problems ({problems(found)})")
check_(any(f.text.startswith("Outside size") for f in found), "its outside size is listed")
check_(took < 10, f"the check of a 12-profile cube takes {took:.1f} s")

# --- Ends that meet without a joint, and a vertex 0.2 mm off ------------------------------------
doc = App.newDocument("pbcheck2")
lines = lines_object(doc, "L", [((0, 0, 0), (300, 0, 0)), ((300, 0, 0), (300, 200, 0)),
                                ((150, 0.2, 0), (150, 200, 0))])
a, b, post = on_edges(doc, lines)
found = check.unjoined(doc)
texts = [f.text for f in found]
check_(any("meets" in t and "has no joint" in t for t in texts), f"a corner without a joint is found ({texts})")
# Distances follow the system locale, so the separator may be a comma.
check_(any(("0.2" in t or "0,2" in t) and "snap the sketch vertex" in t for t in texts), "the post 0.2 mm off is found")
check_(len(found) == 2, f"each problem once ({len(found)})")
clash = check.clashes(doc)
check_(any(a.Label in f.text and b.Label in f.text for f in clash), f"the unjoined corner overlaps ({clash})")
corner = [f for f in found if "meets" in f.text][0]
message = check.apply_fix(doc, corner)
doc.recompute()
check_("1 joint" in message and a.EndJoint is not None and b.StartJoint is not None, f"fix: joined ({message})")
near = [f for f in check.unjoined(doc) if "snap" in f.text][0]
message = check.apply_fix(doc, near)
doc.recompute()
check_(post.StartJoint is not None and not check.unjoined(doc), f"fix: the post joined anyway ({message})")
check_(not check.clashes(doc), f"no overlaps left ({check.clashes(doc)})")

# --- Duplicates, broken objects, long and similar pieces, bare edges ----------------------------
dup = feature.make_profile("20-6", 1, 1, 100, doc, edge=(lines, "Edge1"))
doc.recompute()
found = check.duplicates(doc)
check_(len(found) == 1 and found[0].fix == ("delete", [dup.Name]), f"a second profile on an edge ({found})")
dup_name = dup.Name
check.apply_fix(doc, found[0])
doc.recompute()
check_(not check.duplicates(doc) and doc.getObject(dup_name) is None, "fix: the extra profile is deleted")

bad = feature.make_profile("20-6", 1, 1, 100, doc)
bad.SlotOpening = 50
doc.recompute()
bad_label = bad.Label
check_(any(f.severity == "Error" and bad_label in f.text for f in check.run(doc)), "a broken profile is an error")
doc.removeObject(bad.Name)

settings = pricing.get_settings(doc, create=True)
settings.PurchaseMode = "Stock bars"
settings.StockLength = 250
doc.recompute()
found = check.long_pieces(doc)
check_(found and "longer than" in found[0].text, f"pieces longer than a stock bar ({found})")
settings.PurchaseMode = "Cut to size"

pieces = [feature.make_profile("20-6", 1, 1, length, doc) for length in (380, 380.4, 500)]
doc.recompute()
found = check.similar_lengths(doc)
check_(any("380" in f.text and f.severity == "Info" for f in found), f"380 and 380.4 mm ({found})")
for p in pieces:
    doc.removeObject(p.Name)

sketch_like = lines_object(doc, "Five", [((0, 500, 0), (100, 500, 0)), ((100, 500, 0), (100, 600, 0)),
                                         ((0, 700, 0), (100, 700, 0))])
on_edges(doc, sketch_like, count=2)
found = check.bare_edges(doc)
check_(any("Five" in f.text and "1 straight edge" in f.text for f in found), f"an edge without a profile ({found})")

# --- Panels: a crossbar through an in-slot sheet, but not the sheet's own slots -----------------
doc = App.newDocument("pbcheck3")
ring = lines_object(doc, "Ring", [((0, 0, 0), (600, 0, 0)), ((600, 0, 0), (600, 400, 0)),
                                  ((600, 400, 0), (0, 400, 0)), ((0, 400, 0), (0, 0, 0))])
members = on_edges(doc, ring)
joints.create_joints(doc, members)
sheet = panels.make_panel(doc, members, CutTolerance=0)
doc.recompute()
check_(not check.clashes(doc), f"an in-slot sheet does not clash with its own profiles ({check.clashes(doc)})")
bar = feature.make_profile("20-6", 1, 1, 380, doc)
bar.Placement = App.Placement(V(300, 10, 0), App.Rotation(V(1, 0, 0), -90))
doc.recompute()
found = check.clashes(doc)
check_(any(sheet.Label in f.text and bar.Label in f.text for f in found), f"a crossbar through the sheet ({found})")
sheet.MinTemperature = -40
sheet.Clearance = 2
doc.recompute()
check_(any("can come out" in f.text for f in check.panel_fit(doc)), "panel fit warnings are listed")

# --- Review fixes -------------------------------------------------------------------------------
doc = App.newDocument("pbcheck4")
# A corner whose vertices just miss: one finding, and the fix makes a corner, not a T.
lines = lines_object(doc, "Corner", [((-300, 0, 0), (-0.2, 0.3, 0)), ((0, 0, 0), (0, 200, 0))])
a, b = on_edges(doc, lines)
found = check.unjoined(doc)
check_(len(found) == 1, f"one finding for one corner ({[f.text for f in found]})")
check.apply_fix(doc, found[0])
doc.recompute()
joint = a.EndJoint
check_(joint is not None and b.StartJoint == joint and b.Name not in joint.PassingMembers
       and not check.unjoined(doc), f"the fix joined both ends in one corner joint ({joint and joint.PassingMembers})")

# Three ends: two rails meet, a post starts 0.5 mm above them. Every fix works; nothing is left.
lines = lines_object(doc, "Three", [((1000, 0, 0), (1300, 0, 0)), ((1000, 0, 0), (1000, 300, 0)),
                                    ((1000, 0, 0.5), (1000, 0, 300))])
three = on_edges(doc, lines)
for _round in range(4):
    found = [f for f in check.unjoined(doc) if set(f.objects) & {p.Name for p in three}]
    if not found:
        break
    check.apply_fix(doc, found[0])
    doc.recompute()
check_(not found and all(p.StartJoint is not None for p in three), f"three near ends all joined ({found})")

# Collinear bars spliced end to end, and a corner trimmed by hand: no joint needed, no warning.
lines = lines_object(doc, "Splice", [((0, 1000, 0), (300, 1000, 0)), ((300, 1000, 0), (600, 1000, 0))])
on_edges(doc, lines)
lines = lines_object(doc, "Trimmed", [((0, 2000, 0), (300, 2000, 0)), ((300, 2000, 0), (300, 2300, 0))])
t1, t2 = on_edges(doc, lines)
t1.ExtendEnd, t2.ExtendStart = 10, -10
doc.recompute()
texts = [f.text for f in check.unjoined(doc)]
check_(not texts, f"collinear and hand-trimmed ends are not reported as overlaps ({texts})")

# Deleting a duplicate keeps the copy that a panel uses.
ring = lines_object(doc, "DupRing", [((0, 3000, 0), (400, 3000, 0)), ((400, 3000, 0), (400, 3300, 0)),
                                     ((400, 3300, 0), (0, 3300, 0)), ((0, 3300, 0), (0, 3000, 0))])
first = on_edges(doc, ring)
second = on_edges(doc, ring)
joints.create_joints(doc, second)
sheet = panels.make_panel(doc, second)
doc.recompute()
for finding in check.duplicates(doc):
    check.apply_fix(doc, finding)
doc.recompute()
check_(sheet.isValid() and all(doc.getObject(p.Name) is not None for p in second),
       "the duplicates the panel uses are kept")

# Tiny distances stay readable in inches.
schema = App.Units.getSchema()
try:
    App.Units.setSchema(3)  # Imperial decimal
    text = check.fine(0.2)
    check_(text.endswith("in") and "787" in text, f"0.2 mm in inches ({text})")
finally:
    App.Units.setSchema(schema)

# --- Distances follow the unit schema -----------------------------------------------------------
schema = App.Units.getSchema()
try:
    App.Units.setSchema(3)  # Imperial decimal
    text = check.overall(doc)[0].text
    check_("in" in text or '"' in text, f"sizes in the user's units ({text})")
finally:
    App.Units.setSchema(schema)

print(f"\n{len(failures)} failure(s)")
for f in failures:
    print("  " + f)

# A non-zero exit code lets CI see failures; os._exit skips FreeCAD's own exit handling.
sys.stdout.flush()
os._exit(1 if failures else 0)
