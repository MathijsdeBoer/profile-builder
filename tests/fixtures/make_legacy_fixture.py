"""Build legacy_<commit>.FCStd with an older version of the workbench.

The fixtures check that documents saved by older versions still open
correctly: legacy_8733122 (the first version) and legacy_ead3f7d. To rebuild
one (only needed if the fixture must change), for example for ead3f7d:

    git worktree add --detach ../pb-old ead3f7d
    cd ../pb-old
    PB_FIXTURE_NAME=legacy_ead3f7d PB_FIXTURE_DIR=<this repo>/tests/fixtures \\
        freecadcmd <this repo>/tests/fixtures/make_legacy_fixture.py
    git worktree remove ../pb-old

Run it from the old worktree: it loads the workbench from the current directory,
and refuses to run when it finds the current code instead (FreeCAD may have an
installed copy loaded already). It writes the document and a JSON file with the
values that version computed.
"""

import json
import os
import sys

import freecad

OLD = os.getcwd()  # the worktree of the old version
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None
# FreeCAD may already have loaded an installed (current) copy of the workbench,
# for example through a link in its Mod folder. Drop it and load the old one.
for _name in [m for m in sys.modules if m == "freecad.profile_builder" or m.startswith("freecad.profile_builder.")]:
    del sys.modules[_name]
freecad.__path__.insert(0, os.path.join(OLD, "freecad"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402

from freecad.profile_builder import feature, joints, panels, pricing  # noqa: E402

if not os.path.normcase(os.path.realpath(feature.__file__)).startswith(os.path.normcase(os.path.realpath(OLD))):
    raise SystemExit(f"loaded {feature.__file__}, not the old version in {OLD}")
if hasattr(feature, "needs_refresh") or hasattr(joints, "_live"):
    raise SystemExit("this is not the old version: it already has the newer joint and profile code")

OUT = os.environ.get("PB_FIXTURE_DIR") or HERE
doc = App.newDocument("legacy")


def lines_object(name, pts):
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = Part.makeCompound([Part.makeLine(App.Vector(*a), App.Vector(*b))
                                   for a, b in zip(pts, pts[1:] + pts[:1])])
    return obj


square = lines_object("Square", [(0, 0, 0), (400, 0, 0), (400, 400, 0), (0, 400, 0)])
ring = lines_object("Ring", [(0, 600, 0), (300, 600, 0), (300, 800, 0), (0, 800, 0)])
doc.recompute()
sides = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(square, f"Edge{i + 1}")) for i in range(4)]
frame = [feature.make_profile("20-6", 1, 1, 100, doc, edge=(ring, f"Edge{i + 1}")) for i in range(4)]
for i, p in enumerate(sides):
    p.Label = f"Side {i + 1}"
for i, p in enumerate(frame):
    p.Label = f"Frame {i + 1}"
sides[3].SlotOpening = 6.0  # a customised dimension, which later versions must keep
doc.recompute()
joints.create_joints(doc, sides, "Butt", "Longest")
joints.create_joints(doc, frame, "Miter", "Longest")
doc.recompute()
swapped = sides[0].StartJoint
joints.swap(swapped)  # stored by label in this version
doc.recompute()
glass = panels.make_panel(doc, frame)
glass.Material = "Clear glass"  # this version does not set Density from the material
glass.Density = 2.4  # a value the user typed
doc.recompute()
settings = pricing.get_settings(doc, create=True)
settings.ProfilePrices = {"2020 (20-6)": "12.5"}
doc.recompute()

expected = {
    "lengths": {p.Name: round(p.Length.Value, 6) for p in sides + frame},
    "saw": {p.Name: round(p.OverallLength.Value, 6) for p in sides + frame},
    "miters": {p.Name: [p.MiterStart.Value, p.MiterEnd.Value] for p in frame},
    "swapped_joint": swapped.Name,
    "through": swapped.Through,
    "panel": glass.Name,
    "panel_size": [round(glass.Width.Value, 6), round(glass.Height.Value, 6)],
    "custom": {sides[3].Name: {"SlotOpening": 6.0}},
}
NAME = os.environ.get("PB_FIXTURE_NAME", "legacy_ead3f7d")
doc.saveAs(os.path.join(OUT, f"{NAME}.FCStd"))
with open(os.path.join(OUT, f"{NAME}.json"), "w", encoding="utf-8") as f:
    json.dump(expected, f, indent=1)
print("fixture written", expected["through"])
