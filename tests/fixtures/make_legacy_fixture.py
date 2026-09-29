"""Build legacy_ead3f7d.FCStd with the version at commit ead3f7d.

The fixture checks that documents saved by that version still open correctly.
To rebuild it (only needed if the fixture must change):

    git worktree add --detach ../pb-ead3f7d ead3f7d
    cd ../pb-ead3f7d
    freecadcmd <this repo>/tests/fixtures/make_legacy_fixture.py
    git worktree remove ../pb-ead3f7d

It writes the document and a JSON file with the lengths that version computed.
"""

import json
import os

import freecad

OLD = os.getcwd()  # the worktree of the old version
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None
freecad.__path__.append(os.path.join(OLD, "freecad"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402

from freecad.profile_builder import feature, joints, panels, pricing  # noqa: E402

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
}
doc.saveAs(os.path.join(OUT, "legacy_ead3f7d.FCStd"))
with open(os.path.join(OUT, "legacy_ead3f7d.json"), "w", encoding="utf-8") as f:
    json.dump(expected, f, indent=1)
print("fixture written", expected["through"])
