"""Test slot alignment on adjoining extrusion profiles with FreeCAD's console."""

import os
import sys
import tempfile

import freecad

ROOT = os.getcwd()
for _name in [m for m in sys.modules if m == "freecad.profile_builder" or m.startswith("freecad.profile_builder.")]:
    del sys.modules[_name]
freecad.__path__.insert(0, os.path.join(ROOT, "freecad"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402

from freecad.profile_builder import brackets, check as frame_check, feature, joints, slot_alignment  # noqa: E402

_loaded = os.path.normcase(os.path.realpath(feature.__file__))
if not _loaded.startswith(os.path.normcase(os.path.realpath(ROOT))):
    raise SystemExit(f"testing the wrong copy of the workbench: {_loaded} is not under {ROOT}")
print(f"testing {os.path.dirname(_loaded)}")

failures = []


def check(condition, message):
    print(("ok   " if condition else "FAIL ") + message)
    if not condition:
        failures.append(message)


V = App.Vector


def lines_object(doc, name, segments):
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = Part.makeCompound([Part.makeLine(V(*start), V(*end)) for start, end in segments])
    return obj


doc = App.newDocument("slot_alignment_single")
doc.UndoMode = 1
lines = lines_object(doc, "SingleJoint", [((0, 0, 0), (400, 0, 0)),
                                           ((0, 0, 0), (0, 0, 300))])
rail = feature.make_profile("20-6", 2, 2, 100, doc, edge=(lines, "Edge1"))
post = feature.make_profile("20-6", 1, 3, 100, doc, edge=(lines, "Edge2"))
post.Spin = 90
doc.recompute()
single_joints = joints.create_joints(doc, (rail, post), "Butt", "Longest")
doc.recompute()
joint = single_joints[0]
check("SectionOffsetX" not in post.PropertiesList and "SectionOffsetY" not in post.PropertiesList,
      "unmodified profiles do not acquire offset properties")
before, notes = brackets.joint_spots(joint, "All open faces", brackets.FrameInfo([joint]))
check(not before and any("do not line up" in note for note in notes),
      f"4040 and 2060 slot pitches do not align before the tool ({notes})")
section = (post.Ix, post.Iy, post.Wx, post.Wy)
alignments, notes = slot_alignment.plan([post])
check(len(alignments) == 1 and not notes and alignments[0].matches == 2
      and alignments[0].matched_joints == 1 and abs(alignments[0].spin) < 1e-7,
      f"the plan rotates and offsets the 2060 post to match both 4040 slots ({alignments}, {notes})")
changed = slot_alignment.apply(doc, alignments)
after, notes = brackets.joint_spots(joint, "All open faces", brackets.FrameInfo([joint]))
check(len(changed) == 1 and len(after) == 2 and not notes,
      f"the butt joint now has two slot-aligned bracket positions ({len(after)}, {notes})")
offset = feature.section_offset(post)
check("SectionOffsetX" in post.PropertiesList and "SectionOffsetY" in post.PropertiesList
      and abs(offset.x) < 1e-7 and abs(abs(offset.y) - 10) < 1e-7,
      f"the 2060 section is shifted by half a 20 mm cell ({offset.x}, {offset.y})")
check((post.Ix, post.Iy, post.Wx, post.Wy) == section,
      "a section offset does not change the profile's section properties")
envelope = frame_check._envelope(post).BoundBox
check(abs((envelope.XMin + envelope.XMax) / 2 - post.SectionOffsetX.Value) < 1e-7
      and abs((envelope.YMin + envelope.YMax) / 2 - post.SectionOffsetY.Value) < 1e-7
      and abs(envelope.XLength - 20) < 1e-7 and abs(envelope.YLength - 60) < 1e-7,
      f"the frame-check envelope includes the local section offset ({envelope})")
post_name, joint_name = post.Name, joint.Name
with tempfile.TemporaryDirectory() as folder:
    path = os.path.join(folder, "slot_alignment.FCStd")
    doc.saveAs(path)
    doc.undo()
    doc.recompute()
    offset = feature.section_offset(post)
    check(abs(post.Spin.Value - 90) < 1e-7 and abs(offset.x) < 1e-7 and abs(offset.y) < 1e-7,
          f"slot alignment is one undoable transaction ({post.Spin.Value}, {offset.x}, {offset.y})")
    App.closeDocument(doc.Name)
    doc = App.openDocument(path)
    saved_post = doc.getObject(post_name)
    saved_joint = doc.getObject(joint_name)
    saved_offset = feature.section_offset(saved_post)
    saved_slots, saved_notes = brackets.joint_spots(
        saved_joint, "All open faces", brackets.FrameInfo([saved_joint]))
    check(abs(saved_post.Spin.Value) < 1e-7 and abs(saved_offset.x) < 1e-7
          and abs(abs(saved_offset.y) - 10) < 1e-7 and len(saved_slots) == 2 and not saved_notes,
          "section offsets and aligned slots survive save and reload")
    for _ in range(2):
        if saved_joint.ThroughName == saved_post.Name:
            break
        joints.swap(saved_joint)
        doc.recompute()
    check(saved_joint.ThroughName == saved_post.Name, "the aligned post can be the manual through profile")
    doc.removeObject(saved_post.Name)
    doc.recompute()
    check(saved_joint.ThroughRule != "Manual" and not saved_joint.ThroughName,
          "deleting an aligned through profile resets its joint")
    App.closeDocument(doc.Name)


doc = App.newDocument("slot_alignment_square")
segments = [
    ((0, 0, 0), (400, 0, 0)),
    ((400, 0, 0), (400, 400, 0)),
    ((400, 400, 0), (0, 400, 0)),
    ((0, 400, 0), (0, 0, 0)),
    ((0, 0, 0), (0, 0, 300)),
    ((400, 0, 0), (400, 0, 300)),
    ((400, 400, 0), (400, 400, 300)),
    ((0, 400, 0), (0, 400, 300)),
]
lines = lines_object(doc, "Square", segments)
rails = [feature.make_profile("20-6", 2, 2, 100, doc, edge=(lines, f"Edge{i}"))
         for i in range(1, 5)]
posts = [feature.make_profile("20-6", 1, 3, 100, doc, edge=(lines, f"Edge{i}"))
         for i in range(5, 9)]
for post in posts:
    post.Spin = 90
doc.recompute()
square_joints = joints.create_joints(doc, rails + posts, "Butt", "Longest")
doc.recompute()
plans, notes = slot_alignment.plan(posts)
check(len(square_joints) == 4 and len(plans) == 4 and not notes
      and all(plan.matches == 3 and plan.matched_joints == 1 for plan in plans),
      f"the four posts can align to both adjoining base rails ({plans}, {notes})")
slot_alignment.apply(doc, plans)
corners = ((0, 0), (400, 0), (400, 400), (0, 400))
inward = []
for post, (x, y) in zip(posts, corners):
    inside = V(200 - x, 200 - y, 0)
    inward.append(feature.member_frame(post).center_offset().dot(inside) > 0)
check(all(inward), f"each post shifts toward the inside of the square ({inward})")
joint_results = [brackets.joint_spots(joint, "All open faces", brackets.FrameInfo([joint]))
                 for joint in square_joints]
check(all(not any("do not line up" in note for note in notes) for _places, notes in joint_results),
      "slot alignment clears the slot-mismatch warnings at the four corners")
App.closeDocument(doc.Name)

print(f"{len(failures)} failure(s)")
sys.stdout.flush()
os._exit(1 if failures else 0)
