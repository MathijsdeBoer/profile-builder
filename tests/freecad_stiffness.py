"""Frame stiffness tests on real documents. Run from the repo root with:  freecadcmd tests/freecad_stiffness.py"""

import os
import sys
import tempfile
import time

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

from freecad.profile_builder import cutlist, feature, frame_stiffness as fs, joints, panels  # noqa: E402

_loaded = os.path.normcase(os.path.realpath(fs.__file__))
if not _loaded.startswith(os.path.normcase(os.path.realpath(ROOT))):
    raise SystemExit(f"testing the wrong copy of the workbench: {_loaded} is not under {ROOT}")
print(f"testing {os.path.dirname(_loaded)}")

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def rel(a, b):
    return abs(a - b) / abs(b)


def lines_object(doc, name, segments):
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = Part.makeCompound([Part.makeLine(App.Vector(*a), App.Vector(*b)) for a, b in segments])
    return obj


def framed(doc, name, segments, series="20-6", cols=1, rows=1, rule="Vertical"):
    lines = lines_object(doc, name, segments)
    doc.recompute()
    members = [feature.make_profile(series, cols, rows, 100, doc, edge=(lines, f"Edge{i + 1}"))
               for i in range(len(segments))]
    doc.recompute()
    joints.create_joints(doc, members, "Butt", rule)
    doc.recompute()
    return lines, members


schema = App.Units.getSchema()
App.Units.setSchema(0)  # Standard (mm, kg, s, °) while checking values

# ---- a portal of 2040 profiles against the closed form ------------------------------------

doc = App.newDocument("portal")
H, L = 500.0, 600.0
_lines, (left, rail, right) = framed(doc, "Portal", [((0, 0, 0), (0, 0, H)), ((0, 0, H), (L, 0, H)),
                                                     ((L, 0, H), (L, 0, 0))], rows=2)
check(abs(rail.Length.Value - (L - 20)) < 1e-6, f"portal: rail butts between the posts ({rail.Length.Value})")

E = fs.E_ALUMINIUM
a = E * left.Iy * 1e4 / H  # posts bend about their weak axis in the XZ plane
c = 10.0  # the rail stops at the post faces: rigid end zones
flex = L - 2 * c
b = E * rail.Ix * 1e4 / flex  # the rail stands on edge


def fixed_portal(k=None):
    """Sway stiffness of a fixed-base portal whose rail has rigid end zones c and joint springs k."""
    s = 6 * b * (L / flex) ** 2 if k is None else 6 * b * k * (L / flex) ** 2 / (k + 6 * b)
    return 24 * a * (a + s) / (H ** 2 * (4 * a + s))


result = fs.analyse(doc, {"Supports": "Fixed", "LooseJointFactor": 0.5, "StiffJointFactor": 0.0, "TopMass": 0.0})
loose, stiff = result["bounds"]["loose"], result["bounds"]["stiff"]
check(rel(stiff["x"], fixed_portal()) < 5e-3, f"portal, rigid joints: {stiff['x']:.3f} N/mm vs {fixed_portal():.3f}")
k = 0.5 * E * rail.Ix * 1e4 / L
check(rel(loose["x"], fixed_portal(k)) < 5e-3, f"portal, loose joints: {loose['x']:.3f} N/mm vs {fixed_portal(k):.3f}")
check(result["supports"] == 2 and result["top"] == 2 and result["members"] == 3 and result["joints"] == 2,
      f"portal: 2 supports, 2 loaded nodes, 3 members, 2 joints ({result['supports']}, {result['top']}, "
      f"{result['members']}, {result['joints']})")
check(loose["flex"]["x"]["joints"] > 0.05 and stiff["flex"]["x"]["joints"] == 0,
      f"portal: the joints flex only when not rigid ({loose['flex']['x']['joints']:.2f})")
check(abs(result["mass"] - sum(p.Mass for p in (left, rail, right))) < 1e-9, f"portal: mass {result['mass']:.3f} kg")

# Pinned feet: a flat portal can fall over sideways, which is reported, not solved.
result = fs.analyse(doc, {"Supports": "Pinned"})
mech = result["bounds"]["stiff"]["mechanism"] or ""
check("mechanism" in mech and left.Label in mech and result["bounds"]["stiff"]["x"] is None,
      f"pinned portal: mechanism reported ({mech})")
check("mechanism" in fs.report_text(result), "pinned portal: the report says so")
check(not result["notes"], f"portal: feet on the floor are supports, not free ends ({result['notes']})")

# An arm sticking out at the top has a free end, which the report mentions.
arm_lines = lines_object(doc, "Arm", [((0, 0, H), (-200, 0, H))])
doc.recompute()
arm = feature.make_profile("20-6", 1, 1, 100, doc, edge=(arm_lines, "Edge1"))
doc.recompute()
joints.create_joints(doc, [arm, left, rail, right], "Butt", "Vertical")
doc.recompute()
result = fs.analyse(doc, {"Supports": "Fixed"})
check(arm.StartJoint is not None and any("1 profile end(s) above the supports" in n for n in result["notes"]),
      f"arm: its free end is mentioned ({result['notes']})")

# ---- a 400 mm cube of 2020 --------------------------------------------------------------

doc = App.newDocument("cube")
S = 400
corners = [(0, 0), (S, 0), (S, S), (0, S)]
segments = []
for z in (0, S):
    segments += [((*p, z), (*q, z)) for p, q in zip(corners, corners[1:] + corners[:1])]
segments += [((*p, 0), (*p, S)) for p in corners]
cube_lines, cube = framed(doc, "Cube", segments)
posts = cube[8:]

t0 = time.perf_counter()
result = fs.analyse(doc)
elapsed = time.perf_counter() - t0
loose, stiff = result["bounds"]["loose"], result["bounds"]["stiff"]
check(not loose["mechanism"] and not stiff["mechanism"], "cube: no mechanism with pinned feet")
check(result["supports"] == 4 and result["top"] == 4, "cube: pinned at the 4 lowest nodes, loaded at the top 4")
check(0 < loose["x"] < stiff["x"] and 0 < loose["twist"] < stiff["twist"],
      f"cube: loose joints are softer ({loose['x']:.3f} < {stiff['x']:.3f} N/mm)")
check(rel(loose["x"], loose["y"]) < 1e-6 and rel(stiff["x"], stiff["y"]) < 1e-6, "cube: as stiff in X as in Y")
freqs = [m[0] for m in stiff["modes"]]
check(len(freqs) == 3 and freqs == sorted(freqs) and freqs[0] > 0, f"cube: three frequencies ({freqs})")
labels = [m[1] for m in stiff["modes"]]
check(labels[0].startswith("sways") and labels[1].startswith("sways") and rel(freqs[0], freqs[1]) < 1e-3,
      f"cube: the first two modes sway, at the same frequency ({labels})")
check(elapsed < 5, f"cube: analysed in {elapsed:.2f} s")
check(abs(result["mass"] - sum(p.Mass for p in cube)) < 1e-9, "cube: mass of the profiles")
# Sideways, the two faces along X are closed rectangles on pinned corners: the
# bottom rail holds the post feet as the top rail holds their heads. The rails
# stop 10 mm short of the post centres (rigid end zones) and may hang on
# springs; the rails along Y only add a little torsion, which is left out here.
ei = E * cube[0].Ix * 1e4
a, flex = ei / S, S - 20
b6 = 6 * ei * S ** 2 / flex ** 3


def pinned_cube(k=None):
    s = b6 if k is None else 6 * (ei / flex) * k * (S / flex) ** 2 / (k + 6 * ei / flex)
    return 2 * 24 * a * s / ((6 * a + s) * S ** 2)


check(rel(stiff["x"], pinned_cube()) < 0.01, f"cube, rigid joints: {stiff['x']:.2f} N/mm vs {pinned_cube():.2f}")
check(rel(loose["x"], pinned_cube(0.5 * ei / S)) < 0.01,
      f"cube, loose joints: {loose['x']:.2f} N/mm vs {pinned_cube(0.5 * ei / S):.2f}")

# Fixed feet are stiffer than pinned ones.
fixed = fs.analyse(doc, {"Supports": "Fixed"})
check(fixed["bounds"]["stiff"]["x"] > stiff["x"], "cube: fixed feet are stiffer than pinned")

# Mass on top lowers the frequencies and leaves the stiffness alone.
heavy = fs.analyse(doc, {"TopMass": 10.0})
check(heavy["bounds"]["stiff"]["modes"][0][0] < freqs[0] and rel(heavy["bounds"]["stiff"]["x"], stiff["x"]) < 1e-9,
      f"cube: 10 kg on top lowers mode 1 to {heavy['bounds']['stiff']['modes'][0][0]:.1f} Hz")

# The report: two bounds, unit strings, the estimate note.
text = fs.report_text(result)
check("Loose joints" in text and "Stiff joints" in text and "Estimates" in text and "N/m" in text and "Hz" in text,
      "cube: report text")
html = fs.report_html(result)
check("<table" in html and "Estimates" in html and "Incomplete" not in html, "cube: report html")

# ---- baseline and variants ------------------------------------------------------------

settings = fs.get_settings(doc, create=True)
fs.set_baseline(doc, result)
base = fs.baseline(doc)
check(base is not None and rel(base["bounds"]["stiff"]["x"], stiff["x"]) < 1e-12, "baseline stored")
check(settings.BaselineInfo and "Sideways" in settings.BaselineInfo[0],
      f"baseline summary ({settings.BaselineInfo[:1]})")

for p in posts:
    p.Series = "30-8"
doc.recompute()
cutlist.recompute_if_needed(doc)
bigger = fs.analyse(doc)
rows = {r[0]: r for r in fs.report_rows(bigger, base)}
ratio = rows["Sideways stiffness, X"][3]
check(bigger["bounds"]["loose"]["x"] > loose["x"] and bigger["bounds"]["stiff"]["x"] > stiff["x"]
      and ratio.endswith("×"), f"3030 posts are stiffer: {ratio}")
check(bigger["mass"] > result["mass"] and any("against the baseline" in x for x in fs.summary_lines(bigger, base)),
      "variant: mass change against the baseline")

path = os.path.join(tempfile.gettempdir(), "pb_stiffness.FCStd")
doc.saveAs(path)
App.closeDocument(doc.Name)
doc = App.openDocument(path)
check(fs.baseline(doc) is not None and fs.is_settings(fs.get_settings(doc)), "baseline survives save and reload")
reloaded = fs.analyse(doc)
check(rel(reloaded["bounds"]["stiff"]["x"], bigger["bounds"]["stiff"]["x"]) < 1e-9, "same result after reload")
fs.clear_baseline(doc)
check(fs.baseline(doc) is None and not fs.get_settings(doc).BaselineInfo, "baseline cleared")

# ---- things the model leaves out, and says so ---------------------------------------------------

cube = [o for o in doc.Objects if feature.is_profile(o)]
free = feature.make_profile("20-6", 1, 1, 300, doc)  # not on a sketch edge
loose_lines = lines_object(doc, "Floating", [((1000, 0, 100), (1000, 300, 100))])
doc.recompute()
floating = feature.make_profile("20-6", 1, 1, 100, doc, edge=(loose_lines, "Edge1"))
doc.recompute()
result = fs.analyse(doc)
excluded = " ".join(result["excluded"])
check(free.Label in excluded and "not on a sketch edge" in excluded, f"free profile left out ({result['excluded']})")
check(floating.Label in excluded and "not connected" in excluded, "floating profile left out")
check("Incomplete" in fs.report_html(result), "the panel says the model is incomplete")
doc.removeObject(free.Name)
doc.removeObject(floating.Name)

# A profile with an error is left out.
broken = cube[0]
broken.SlotOpening = 30
doc.recompute()
result = fs.analyse(doc)
check(any(broken.Label in e for e in result["excluded"]), "profile with an error left out")
broken.SlotOpening = 6.2
doc.recompute()

# Panels add their mass to the frame.
side = [p for p in cube if abs(feature.member_frame(p).z.y) < 1e-6 and
        all(abs(v.Point.y) < 1e-6 for v in feature.path_edge(p).Vertexes)]
before = fs.analyse(doc)
sheet = panels.make_panel(doc, side, Mount="On face")
doc.recompute()
after = fs.analyse(doc)
check(sheet.isValid() and abs(after["mass"] - before["mass"] - sheet.Mass) < 1e-9,
      f"panel mass counted ({sheet.Mass:.2f} kg)")
check(after["bounds"]["stiff"]["modes"][0][0] < before["bounds"]["stiff"]["modes"][0][0],
      "the panel's mass lowers the frequency (its bracing is not modelled)")

# ---- a frame with a middle rail: T-junctions split the rail they pass through ------------------

doc = App.newDocument("tee")
W = 600
segs = [((0, 0, 0), (0, 0, 400)), ((W, 0, 0), (W, 0, 400)), ((0, 0, 400), (W, 0, 400)),
        ((W / 2, 0, 400), (W / 2, 0, 0))]
_l, tee = framed(doc, "Tee", segs, rule="Longest")
t_joint = [o for o in doc.Objects if joints.is_joint(o) and o.PassingMembers]
check(len(t_joint) == 1, "tee: one T-junction")
result = fs.analyse(doc, {"Supports": "Fixed"})
check(result["supports"] == 3 and result["top"] == 3 and result["joints"] == 3,
      f"tee: 3 supports and 3 loaded nodes ({result['supports']}, {result['top']}, {result['joints']})")
three = result["bounds"]["stiff"]["x"]
doc.removeObject(tee[3].Name)
doc.recompute()
two = fs.analyse(doc, {"Supports": "Fixed"})["bounds"]["stiff"]["x"]
check(three > two * 1.2, f"tee: the middle post adds stiffness ({two:.2f} -> {three:.2f} N/mm)")

# ---- the task panel, without the GUI running ------------------------------------------------------

try:
    from PySide import QtWidgets  # noqa: E402
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from freecad.profile_builder import frame_ui  # noqa: E402
    gdoc = App.newDocument("panel")
    gdoc.UndoMode = 1
    doc = gdoc
    framed(gdoc, "PanelCube", segments)
    panel = frame_ui.FrameStiffnessPanel(gdoc)
    check("<table" in panel.view.text() and "Estimates" in panel.view.text() and fs.get_settings(gdoc) is not None,
          "panel: shows the results and makes its settings object")
    check(panel.stiff.text() == "rigid" and not panel.clear_button.isEnabled(), "panel: stiff joints shown as rigid")
    first = panel.result["bounds"]["loose"]["x"]
    panel.loose.setValue(2.0)
    panel.supports.setCurrentIndex(panel.supports.findData("Fixed"))
    panel.apply()
    s = fs.get_settings(gdoc)
    check(s.LooseJointFactor == 2.0 and s.Supports == "Fixed" and panel.result["bounds"]["loose"]["x"] > first,
          "panel: settings are applied and the results follow")
    panel.top_mass.setText("11 lb")
    panel._mass_edited()
    panel.apply()
    check(abs(s.TopMass.Value - 4.98951607) < 1e-6, f"panel: mass on top typed in pounds ({s.TopMass.Value:.3f} kg)")
    panel.top_mass.setText("heavy")
    panel._mass_edited()
    panel.apply()
    check("c33" in panel.top_mass.styleSheet() and abs(s.TopMass.Value - 4.98951607) < 1e-6,
          "panel: an invalid mass is marked and not used")
    panel.set_button.click()
    check(fs.baseline(gdoc) is not None and panel.clear_button.isEnabled() and "Against baseline" in panel.view.text(),
          "panel: set as baseline")
    panel.clear_button.click()
    check(fs.baseline(gdoc) is None and not panel.clear_button.isEnabled(), "panel: clear baseline")
    gdoc.abortTransaction()
    check(fs.get_settings(gdoc) is None, "panel: Cancel removes the settings object it made")
    command = frame_ui.FrameStiffness().GetResources()
    check(os.path.exists(command["Pixmap"]), "command icon exists")
    empty = App.newDocument("empty")
    panel = frame_ui.FrameStiffnessPanel(empty)
    check("no profiles" in panel.view.text() and not panel.set_button.isEnabled(),
          f"panel: an empty document gets a message ({panel.view.text()[:60]})")
    empty.abortTransaction()
except ImportError as e:
    check(False, f"panel test could not run: {e}")

# ---- units --------------------------------------------------------------------------------

check(fs.quantity(5.0, "stiffness") in ("5.00 kN/m", "5,00 kN/m"),
      f"stiffness in kN/m ({fs.quantity(5.0, 'stiffness')})")
check(fs.twist_text(1e6 * 180 / 3.141592653589793).endswith("N·m/°"), f"twist ({fs.twist_text(1e6)})")
check(fs.parse_mass("5 kg") == 5.0 and abs(fs.parse_mass("11 lb") - 4.98951607) < 1e-6 and fs.parse_mass("5") == 5.0,
      "mass input: kg, lb, plain number")
check(fs.parse_mass("abc") is None and fs.parse_mass("3 mm") is None and fs.parse_mass("-1 kg") is None,
      "mass input: invalid text is refused")
check(abs(fs.parse_mass(fs.mass_text(2.345)) - 2.345) < 1e-9, f"mass input reads its own text ({fs.mass_text(2.345)})")
App.Units.setSchema(3)  # Imperial decimal
check("lbf/in" in fs.quantity(5.0, "stiffness") and "28" in fs.quantity(5.0, "stiffness"),
      f"imperial stiffness ({fs.quantity(5.0, 'stiffness')})")
check(fs.quantity(2.0, "mass").endswith("lb") and fs.twist_text(1e6).endswith("lbf·ft/°"),
      f"imperial mass and twist ({fs.quantity(2.0, 'mass')}, {fs.twist_text(1e6)})")
check(abs(fs.parse_mass("5") - 5 * 0.45359237) < 1e-6, "imperial: a plain number is in pounds")
App.Units.setSchema(1)  # MKS: no rule for moments
check(fs.twist_text(1e6).endswith("N·m/°"), f"MKS twist falls back to N·m ({fs.twist_text(1e6)})")
App.Units.setSchema(schema)

# Without numpy/scipy the analysis says so instead of failing to import.
package = sys.modules["freecad.profile_builder"]
saved = sys.modules.pop("freecad.profile_builder.frame_model", None), package.__dict__.pop("frame_model", None)
sys.modules["freecad.profile_builder.frame_model"] = None  # makes the import fail
try:
    fs.analyse(gdoc)
    check(False, "no solver: analyse should refuse")
except ValueError as e:
    check("numpy and scipy" in str(e), f"no solver: clear message ({e})")
finally:
    del sys.modules["freecad.profile_builder.frame_model"]
    if saved[0] is not None:
        sys.modules["freecad.profile_builder.frame_model"] = saved[0]
    if saved[1] is not None:
        package.frame_model = saved[1]

print("\n%d failure(s)" % len(failures))
