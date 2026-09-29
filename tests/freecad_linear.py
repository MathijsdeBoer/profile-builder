"""Carriage (linear axis) tests. Run from the repo root with:  freecadcmd tests/freecad_linear.py"""

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

from freecad.profile_builder import feature, joints, linear, panels  # noqa: E402

_loaded = os.path.normcase(os.path.realpath(feature.__file__))
if not _loaded.startswith(os.path.normcase(os.path.realpath(ROOT))):
    raise SystemExit(f"testing the wrong copy of the workbench: {_loaded} is not under {ROOT}")
print(f"testing {os.path.dirname(_loaded)}")

failures = []
V = App.Vector


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def near(a, b, tol=1e-6):
    return abs(a - b) < tol


def lines_object(doc, name, segments):
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = Part.makeCompound([Part.makeLine(V(*a), V(*b)) for a, b in segments])
    return obj


def box_of(obj):
    bb = obj.Shape.BoundBox
    return tuple(round(v, 6) for v in (bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax))


def post_frame(doc, post_series="40-8", rail_z=300):
    """Two 600 mm posts 600 apart along X, and a 2020 rail between them at rail_z (T-junctions)."""
    lines = lines_object(doc, "Posts", [((0, 0, 0), (0, 0, 600)), ((600, 0, 0), (600, 0, 600)),
                                        ((0, 0, rail_z), (600, 0, rail_z))])
    doc.recompute()
    posts = [feature.make_profile(post_series, 1, 1, 100, doc, edge=(lines, f"Edge{i}")) for i in (1, 2)]
    rail = feature.make_profile("20-6", 1, 1, 100, doc, edge=(lines, "Edge3"))
    doc.recompute()
    joints.create_joints(doc, posts + [rail], "Butt", "Vertical")
    doc.recompute()
    return lines, posts, rail


# ---- a rail between two posts --------------------------------------------------

doc = App.newDocument("carriage_posts")
lines, posts, rail = post_frame(doc)
check(near(rail.Length.Value, 560), f"rail between 4040 posts is 560 ({rail.Length.Value})")
car = linear.make_carriage(doc, rail, "Top", CarriageLength=60, EndStopLength=5, RequiredStroke=488)
doc.recompute()
check(car.isValid(), f"carriage builds ({car.getStatusString() if not car.isValid() else ''})")
check(near(car.ClearRun.Value, 560) and near(car.Stroke.Value, 490),
      f"clear run 560, stroke 490 ({car.ClearRun}, {car.Stroke})")
check(car.Warning == "", f"no warning when the stroke is enough ({car.Warning!r})")
check(posts[0].Label in car.Limits and posts[1].Label in car.Limits, f"limited by both posts ({car.Limits})")
check(car.Label2.startswith("Stroke "), f"stroke shown in the tree description ({car.Label2})")
# At 0 % the carriage touches the start end stop; it sits on the top face (world +Z).
check(box_of(car) == (25.0, 85.0, -10.0, 10.0, 310.0, 320.0), f"placed at the start of the stroke ({box_of(car)})")
car.PositionPercent = 100
doc.recompute()
check(box_of(car)[:2] == (515.0, 575.0) and near(car.Travel.Value, 490),
      f"100 % is the end of the stroke ({box_of(car)})")

# The dependency goes one way: the carriage follows the frame, nothing follows the carriage.
check(car.Name not in [o.Name for o in rail.OutListRecursive], "the rail does not depend on the carriage")
check(all(p.Name in [o.Name for o in car.OutList] for p in posts), "the carriage depends on the posts")
check(not [o.Name for o in doc.Objects if "Touched" in o.State], "nothing left touched")

# Posts from 40 to 45: the rail gets shorter and the stroke drops below the requirement.
for p in posts:
    p.Series = "45-8"
doc.recompute()
check(near(rail.Length.Value, 555) and near(car.ClearRun.Value, 555) and near(car.Stroke.Value, 485),
      f"4545 posts: run 555, stroke 485 ({car.ClearRun}, {car.Stroke})")
check(f"{linear.length_text(3)} short of the required" in car.Warning,
      f"warning below the required stroke ({car.Warning})")
check("see Warning" in car.Label2, f"the tree description points at the warning ({car.Label2})")
car.RequiredStroke = 480
doc.recompute()
check(car.Warning == "", "warning gone when the requirement is met")

# Distance mode keeps the carriage where it was, and warns beyond the stroke.
before = box_of(car)
car.PositionMode = "Distance"
check(near(car.Position.Value, 485), f"switching to distance keeps the travel ({car.Position})")
doc.recompute()
check(box_of(car) == before, "and the carriage stays put")
car.Position = 500
doc.recompute()
check("outside the stroke" in car.Warning and posts[1].Label in car.Warning, f"beyond the stroke ({car.Warning})")
car.Position = 100
car.PositionMode = "Percent"
check(near(car.PositionPercent, 100 * 100 / 485, 1e-6), f"switching back gives the percentage ({car.PositionPercent})")
doc.recompute()
check(car.Warning == "", "within the stroke again")

# Undo and Cancel restore the old values without converting them again.
doc.UndoMode = 1
state = (car.PositionMode, car.Position.Value, car.PositionPercent, car.CarriageLength.Value)
doc.openTransaction("edit carriage")
car.PositionMode = "Distance"
car.CarriageLength = 100
doc.recompute()
doc.abortTransaction()
doc.recompute()
check((car.PositionMode, car.Position.Value, car.PositionPercent, car.CarriageLength.Value) == state
      and near(car.Stroke.Value, 485),
      f"abort restores the carriage ({car.PositionMode}, {car.Position}, {car.PositionPercent})")

# An obstacle on the face (a motor mount at the start) shortens the run.
mount = doc.addObject("Part::Box", "MotorMount")
mount.Length, mount.Width, mount.Height = 30, 20, 20
mount.Placement.Base = V(22.5, -10, 310)
car.Obstacles = [mount]
doc.recompute()
check(near(car.ClearRun.Value, 525) and mount.Label in car.Limits,
      f"obstacle limits the run ({car.ClearRun}, {car.Limits})")
car.Obstacles = []
doc.recompute()
check(near(car.ClearRun.Value, 555), "and the run is back without it")

# A body replaces the placeholder box, placed in carriage coordinates.
body = doc.addObject("Part::Box", "CarriagePlate")
body.Length, body.Width, body.Height = 50, 12, 70  # across, out of the face, along the rail
body.Placement.Base = V(1000, 1000, 1000)
car.Body = body
car.BodyPlacement = App.Placement(V(-25, 0, -35), App.Rotation())
car.PositionPercent = 50
doc.recompute()
centre = 22.5 + 5 + 30 + 485 / 2
bb = car.Shape.BoundBox
check(near(bb.XMin, centre - 35) and near(bb.XMax, centre + 35) and near(bb.YMin, -25) and near(bb.ZMin, 310)
      and near(bb.ZMax, 322), f"body placed on the face at the carriage centre ({box_of(car)})")
check(box_of(body) == (1000.0, 1050.0, 1000.0, 1012.0, 1000.0, 1070.0), "the body itself is not moved")
car.Body = None
doc.recompute()

check(linear.face_at(rail, V(300, 0, 310)) == "Top" and linear.face_at(rail, V(300, 10, 300)) == "Right",
      "picked point gives the face")
check(linear.face_at(rail, V(22.5, 0, 300)) is None, "a point on the end face gives no face")

# A second run number that does not exist falls back to the longest, with a note.
car.Run = 3
doc.recompute()
check("no run 3" in car.Warning and near(car.ClearRun.Value, 555), f"missing run number ({car.Warning})")
car.Run = 0
doc.recompute()

# Save and reload: the carriage restores and recomputes to the same values.
path = os.path.join(tempfile.gettempdir(), "pb_carriage.FCStd")
name = car.Name
doc.saveAs(path)
App.closeDocument(doc.Name)
doc = App.openDocument(path)
car = doc.getObject(name)
check(car is not None and car.Rail is not None and near(car.Stroke.Value, 485), "carriage survives reload")
car.touch()
doc.recompute()
check(car.isValid() and near(car.Stroke.Value, 485) and car.Warning == "", "recomputes the same after reload")
car.PositionPercent = 150.0
check(car.PositionPercent <= 100, f"percent limit restored after reload ({car.PositionPercent})")

# A panel sitting in the slot of the carriage's face blocks it along its whole length.
lines = doc.getObject("Posts")
top = lines_object(doc, "Top rail", [((0, 0, 600), (600, 0, 600))])
doc.recompute()
top_rail = feature.make_profile("20-6", 1, 1, 100, doc, edge=(top, "Edge1"))
doc.recompute()
profiles_now = [o for o in doc.Objects if feature.is_profile(o)]
joints.create_joints(doc, profiles_now, "Butt", "Vertical")
doc.recompute()
rail = car.Rail
posts = [o for o in profiles_now if o.Name not in (rail.Name, top_rail.Name)]
sheet = panels.make_panel(doc, [rail, posts[0], top_rail, posts[1]])
doc.recompute()
check(sheet.isValid(),
      f"panel between the rail and the top rail ({sheet.getStatusString() if not sheet.isValid() else ''})")
status = car.getStatusString()
check(not car.isValid() and "blocked along its whole length" in status and sheet.Label in status
      and posts[0].Label not in status, f"panel in the face's slot blocks the carriage ({status})")
car.Face = "Bottom"
doc.recompute()
check(car.isValid() and near(car.ClearRun.Value, 555), f"the bottom face is free ({car.ClearRun})")
App.closeDocument(doc.Name)

# ---- T-junctions in the middle of the rail ----------------------------------------

doc = App.newDocument("carriage_tee")
lines, posts, rail = post_frame(doc)
# The carriage comes first: members added later must still be found.
car = linear.make_carriage(doc, rail, "Top", CarriageLength=60, EndStopLength=5)
doc.recompute()
check(len(car.Runs) == 1 and near(car.ClearRun.Value, 560), "before the T members: one run")
tee = lines_object(doc, "Tees", [((250, 0, 300), (250, 0, 600)), ((400, 0, 300), (400, -300, 300))])
doc.recompute()
upright = feature.make_profile("20-6", 1, 1, 100, doc, edge=(tee, "Edge1"))  # butts on the rail's top face
side = feature.make_profile("20-6", 1, 1, 100, doc, edge=(tee, "Edge2"))  # butts on its -Y (Left) face
doc.recompute()
joints.create_joints(doc, [upright, side, rail], "Butt", "Vertical")
doc.recompute()
check(near(upright.Length.Value, 290) and near(side.Length.Value, 290),
      f"T members butt on the rail ({upright.Length}, {side.Length})")
check(not [o.Name for o in doc.Objects if "Touched" in o.State], "nothing left touched after adding members")
check(len(car.Runs) == 2 and near(car.ClearRun.Value, 320) and near(car.Stroke.Value, 250),
      f"a member on the face splits the run; the longer one is used ({list(car.Runs)})")
check(upright.Label in car.Limits and posts[1].Label in car.Limits, f"run from the T member to the post ({car.Limits})")
check(side.Label not in " ".join(car.Runs), "the member on another face does not block")
check(car.Shape.BoundBox.XMin > 260 - 1e-6, "the carriage is on the longer run")
car.Run = 1
doc.recompute()
check(near(car.ClearRun.Value, 220) and car.Shape.BoundBox.XMax < 240 + 1e-6, f"Run 1 is the first run ({car.ClearRun})")
car.Run = 0
car.Face = "Bottom"
doc.recompute()
check(len(car.Runs) == 1 and near(car.ClearRun.Value, 560), f"the bottom face is not blocked ({list(car.Runs)})")
car.Face = "Right"
car.EnvelopeWidth = 40
doc.recompute()
check(len(car.Runs) == 1 and near(car.ClearRun.Value, 560),
      "a wide carriage on the side face that does not wrap is free")
car.Wrap = 5
doc.recompute()
check(len(car.Runs) == 2 and upright.Label in car.Limits,
      f"wrapping over the top face, it hits the T member ({car.Limits})")
car.Face = "Left"
car.Wrap = 0
car.EnvelopeWidth = 20
doc.recompute()
check(len(car.Runs) == 2 and side.Label in " ".join(car.Runs),
      f"on the left face the side member blocks ({list(car.Runs)})")
# The T member grows: the carriage recomputes after it, although only the T member changed.
car.Face = "Top"
doc.recompute()
upright.Series = "40-8"
doc.recompute()
check(near(car.ClearRun.Value, 310), f"a 4040 T member takes more of the run ({car.ClearRun})")
App.closeDocument(doc.Name)

# ---- a rail that runs through on top of two posts --------------------------------

doc = App.newDocument("carriage_through")
lines = lines_object(doc, "Frame", [((0, 0, 0), (0, 0, 600)), ((600, 0, 0), (600, 0, 600)),
                                    ((0, 0, 600), (600, 0, 600))])
doc.recompute()
members = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(lines, f"Edge{i}")) for i in (1, 2, 3)]
doc.recompute()
joints.create_joints(doc, members, "Butt", "Horizontal")
doc.recompute()
rail = members[2]
check(near(rail.Length.Value, 620), f"through rail extends over the posts ({rail.Length})")
car = linear.make_carriage(doc, rail, "Top", CarriageLength=60)
doc.recompute()
check(near(car.ClearRun.Value, 620) and "the start of" in car.Limits and "the end of" in car.Limits,
      f"on top, the whole rail is free ({car.ClearRun}, {car.Limits})")
car.Face = "Bottom"
doc.recompute()
check(near(car.ClearRun.Value, 580) and members[0].Label in car.Limits and members[1].Label in car.Limits,
      f"underneath, the posts limit it ({car.ClearRun}, {car.Limits})")
App.closeDocument(doc.Name)

# ---- a mitered rail: the face under the carriage decides ------------------------

doc = App.newDocument("carriage_miter")
ring = lines_object(doc, "Ring", [((0, 0, 0), (600, 0, 0)), ((600, 0, 0), (600, 400, 0)),
                                  ((600, 400, 0), (0, 400, 0)), ((0, 400, 0), (0, 0, 0))])
doc.recompute()
sides = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(ring, f"Edge{i}")) for i in (1, 2, 3, 4)]
doc.recompute()
joints.create_joints(doc, sides, "Miter")
doc.recompute()
car = linear.make_carriage(doc, sides[0], "Top", CarriageLength=60)
doc.recompute()
check(near(car.ClearRun.Value, 580), f"full-width carriage on a mitered rail: the short side, 580 ({car.ClearRun})")
car.EnvelopeWidth = 10
doc.recompute()
check(near(car.ClearRun.Value, 590), f"a 10 mm wide carriage: 590 ({car.ClearRun})")
App.closeDocument(doc.Name)

# ---- the task panel ---------------------------------------------------------------

try:
    from PySide import QtWidgets  # noqa: E402
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from freecad.profile_builder import linear_ui  # noqa: E402
    doc = App.newDocument("carriage_panel")
    doc.UndoMode = 1
    _lines, posts, rail = post_frame(doc)
    car = linear.make_carriage(doc, rail, "Top", CarriageLength=60, EndStopLength=5)
    doc.recompute()
    dialog = linear_ui.CarriageTaskPanel(car)
    check(dialog.widgets["Position"].isHidden() and not dialog.widgets["PositionPercent"].isHidden(),
          "panel: percent shown, distance hidden")
    dialog.widgets["PositionMode"].setCurrentText("Distance")
    dialog.widgets["Run"].setValue(1)
    dialog.apply()
    check(car.PositionMode == "Distance" and car.Run == 1 and not dialog.widgets["Position"].isHidden()
          and dialog.widgets["PositionPercent"].isHidden(), "panel: distance mode and run number applied")
    dialog.widgets["Position"].setValue(50)
    dialog.apply()
    check(near(car.Travel.Value, 50) and "Stroke" in dialog.info.text(), f"panel: position applied ({car.Travel})")
    doc.abortTransaction()
    doc.recompute()
    check(car.PositionMode == "Percent" and car.Run == 0, "panel: cancel restores the carriage")
    App.closeDocument(doc.Name)
except ImportError as e:
    check(False, f"panel test could not run: {e}")

print("\n%d failure(s)" % len(failures))
