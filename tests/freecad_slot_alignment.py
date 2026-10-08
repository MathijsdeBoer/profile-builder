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

from freecad.profile_builder import brackets, check as frame_check, feature, joints, linear, slot_alignment  # noqa: E402

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


def slot_face_name(profile, face_name, slot_number):
    for index, _face in enumerate(profile.Shape.Faces, start=1):
        try:
            picked = slot_alignment.picked_slot(profile, f"Face{index}")
        except ValueError:
            continue
        if picked.face == face_name and picked.slot == slot_number:
            return f"Face{index}"
    raise AssertionError(f"no selectable slot floor for {profile.Label} {face_name} slot {slot_number}")


doc = App.newDocument("slot_alignment_single")
doc.UndoMode = 1
lines = lines_object(doc, "SingleJoint", [((120, 50, 30), (520, 50, 30)),
                                           ((120, 50, 30), (120, 50, 330))])
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
rail.MiterAcross = "X"
rail.MiterEnd = 79
doc.recompute()
slot_pairs = slot_alignment.slot_choices([post])[post.Name]
anchor = next(pair for pair in slot_pairs if pair.reference_name == rail.Name)
reference_face_name = slot_face_name(rail, anchor.reference_face, anchor.reference_slot)
picked_reference = slot_alignment.picked_slot(rail, reference_face_name)
picked_pairs = slot_alignment.slot_pairs_for_picked_slots([post], [picked_reference])
picked_alignments, picked_notes = slot_alignment.plan([post], picked_pairs)
check(len(picked_alignments) == 1 and not picked_notes
      and picked_alignments[0].slot_pair.reference_name == rail.Name
      and picked_alignments[0].slot_pair.reference_face == picked_reference.face
      and picked_alignments[0].slot_pair.reference_slot == picked_reference.slot,
      f"a picked reference slot floor on a mitered profile anchors the post alignment "
      f"({picked_alignments}, {picked_notes})")
non_planar = next((index for index, face in enumerate(rail.Shape.Faces, start=1)
                   if type(face.Surface).__name__ != "Plane"), None)
invalid_rejected = False
if non_planar is not None:
    try:
        slot_alignment.picked_slot(rail, f"Face{non_planar}")
    except ValueError:
        invalid_rejected = True
check(invalid_rejected, "a non-planar profile face is rejected as a slot reference")
non_slot_plane_rejected = False
for index, face in enumerate(rail.Shape.Faces, start=1):
    if type(face.Surface).__name__ != "Plane":
        continue
    try:
        slot_alignment.picked_slot(rail, f"Face{index}")
    except ValueError:
        non_slot_plane_rejected = True
        break
check(non_slot_plane_rejected, "a planar lip or side face is rejected as a slot reference")
reference_pairs_by_face = {}
for pair in slot_pairs:
    if pair.reference_name == rail.Name:
        reference_pairs_by_face.setdefault(pair.reference_face, {})[pair.reference_slot] = pair
two_slot_face = next(((face_name, pairs) for face_name, pairs in reference_pairs_by_face.items()
                      if len(pairs) >= 2), None)
multiple_picks_aligned = False
if two_slot_face is not None:
    face_name, pairs = two_slot_face
    selected_slots = [slot_alignment.picked_slot(
        rail, slot_face_name(rail, face_name, slot_number))
        for slot_number in sorted(pairs)[:2]]
    multiple_pairs = slot_alignment.slot_pairs_for_picked_slots([post], selected_slots)
    multiple_alignments, multiple_notes = slot_alignment.plan([post], multiple_pairs)
    multiple_picks_aligned = (len(multiple_alignments) == 1
                              and multiple_alignments[0].matches == len(selected_slots)
                              and not multiple_notes)
check(multiple_picks_aligned, "multiple picked reference slots are honored together")
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
check(abs((envelope.XMin + envelope.XMax) / 2 - (120 + post.SectionOffsetX.Value)) < 1e-7
      and abs((envelope.YMin + envelope.YMax) / 2 - (50 + post.SectionOffsetY.Value)) < 1e-7
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


def picked_floors(profile, across):
    """(PickedSlot, world centre of its floor face) for the slot floors whose face normal is square to ``across``."""
    found = []
    for index, face in enumerate(profile.Shape.Faces, start=1):
        try:
            picked = slot_alignment.picked_slot(profile, f"Face{index}")
        except ValueError:
            continue
        normal = slot_alignment._face_normal(feature.member_frame(profile), picked.face)
        if abs(normal.dot(across)) < 1e-6:
            found.append((picked, face.CenterOfMass))
    return found


def floor_across(profile, picked, across):
    return next(centre for slot, centre in picked_floors(profile, across)
                if (slot.face, slot.slot) == (picked.face, picked.slot)).dot(across)


# Profiles that are not joined: a 2040 rail beside a 4040 post, aligned by picking one slot on each.
for rail_spin in (0, 90):
    doc = App.newDocument("slot_alignment_direct")
    lines = lines_object(doc, "Loose", [((0, 0, 0), (0, 0, 300)), ((100, 13, 150), (300, 13, 150))])
    post = feature.make_profile("20-6", 2, 2, 100, doc, edge=(lines, "Edge1"))
    rail = feature.make_profile("20-6", 1, 2, 100, doc, edge=(lines, "Edge2"))
    rail.Spin = rail_spin
    doc.recompute()
    across = rail.Placement.Rotation.multVec(V(0, 0, 1)).cross(post.Placement.Rotation.multVec(V(0, 0, 1)))
    across.normalize()
    rail_floors = picked_floors(rail, across)
    post_floors = picked_floors(post, across)
    check(bool(rail_floors) and bool(post_floors),
          f"spin {rail_spin}: both profiles have pickable slot floors square to the alignment direction")
    target = rail_floors[0][0]
    reference = post_floors[0][0]
    gap_before = floor_across(post, reference, across) - floor_across(rail, target, across)
    placement_before = (rail.Placement.Base, rail.Length.Value)
    check(abs(gap_before) > 1, f"spin {rail_spin}: the slots start out of line ({gap_before:.3f} mm)")

    plans = slot_alignment.direct_align_slots(target, reference)
    changed = slot_alignment.apply(doc, plans)
    doc.recompute()
    gap_after = floor_across(post, reference, across) - floor_across(rail, target, across)
    check(len(changed) == 1 and abs(gap_after) < 1e-6,
          f"spin {rail_spin}: the picked slots line up without any joint ({gap_after:.6f} mm)")
    check(not [o for o in doc.Objects if joints.is_joint(o)], f"spin {rail_spin}: no joint was created")
    check((rail.Placement.Base - placement_before[0]).Length < 1e-7 and rail.Length.Value == placement_before[1],
          f"spin {rail_spin}: the target keeps its sketch edge and length")
    check(not slot_alignment.direct_align_slots(target, reference)[0].changed,
          f"spin {rail_spin}: aligning again changes nothing")
    App.closeDocument(doc.Name)


def align_picks(first, first_face, first_slot, second, second_face, second_slot):
    """Run what the Align slots command does with two picked slot floors.

    Returns ("refused", message), ("unchanged", None) or ("moved", changed).
    """
    target = slot_alignment.picked_slot(first, slot_face_name(first, first_face, first_slot))
    reference = slot_alignment.picked_slot(second, slot_face_name(second, second_face, second_slot))
    try:
        alignments = slot_alignment.direct_align_slots(target, reference)
    except ValueError as error:
        return "refused", str(error)
    changes = [alignment for alignment in alignments if alignment.changed]
    if not changes:
        return "unchanged", None
    return "moved", slot_alignment.apply(first.Document, changes)


def floor_centre(profile, face_name, slot_number):
    return profile.Shape.Faces[int(slot_face_name(profile, face_name, slot_number)[4:]) - 1].CenterOfMass


def box_of(profile):
    box = profile.Shape.BoundBox
    return (box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax)


def same_box(first, second):
    return all(abs(a - b) < 1e-6 for a, b in zip(first, second))


# Picks whose slots cannot line up along the alignment direction are refused, every time.
doc = App.newDocument("slot_alignment_refused")
lines = lines_object(doc, "Loose", [((0, 0, 0), (0, 0, 300)), ((100, 13, 150), (300, 13, 150))])
post = feature.make_profile("20-6", 2, 2, 100, doc, edge=(lines, "Edge1"))
rail = feature.make_profile("20-6", 1, 2, 100, doc, edge=(lines, "Edge2"))
doc.recompute()
# The rail's Right face points along world Y, the direction the slots would slide.
rail_box = box_of(rail)
results = [align_picks(rail, "Right", 1, post, "Right", 1) for _ in range(3)]
doc.recompute()
check(all(result == "refused" for result, _message in results)
      and "Right face of " + rail.Label in results[0][1],
      f"a target face that points along the alignment direction is refused ({ascii(results[0])})")
check(same_box(box_of(rail), rail_box) and feature.section_offset(rail).Length < 1e-9,
      f"repeating a refused pick does not move the target ({box_of(rail)} vs {rail_box})")
rail.Spin = 90
doc.recompute()
for face in ("Top", "Bottom"):
    result, message = align_picks(rail, "Right", 1, post, face, 1)
    check(result == "refused" and f"{face} face of {post.Label}" in message,
          f"a reference on the post's {face} face is refused ({ascii(message)})")
result, _changed = align_picks(rail, "Right", 1, post, "Right", 2)
doc.recompute()
check(result == "moved" and abs(floor_centre(rail, "Right", 1).y - floor_centre(post, "Right", 2).y) < 1e-6,
      f"the same target lines up with a slot on the post face beside it ({result}, "
      f"{floor_centre(rail, 'Right', 1).y:.6f}, {floor_centre(post, 'Right', 2).y:.6f})")
rail_offset = feature.section_offset(rail)
post.Spin = 33
doc.recompute()
result, message = align_picks(rail, "Right", 1, post, "Right", 1)
check(result == "refused" and message.startswith(post.Label) and "Spin" in message,
      f"a turned reference profile is refused ({ascii(message)})")
check((feature.section_offset(rail) - rail_offset).Length < 1e-9, "a refused turned reference moves nothing")
post.Spin = 0
rail.Spin = 100  # within the old 0.95 limit, but its faces are not square to the post
doc.recompute()
result, message = align_picks(rail, "Right", 1, post, "Right", 1)
check(result == "refused" and message.startswith(rail.Label),
      f"a target turned by 10 degrees is refused ({ascii(message)})")
App.closeDocument(doc.Name)

# Parallel and nearly parallel profiles are lined up across the target face's normal.
for top_y in (7.0, 7.05, 7.5):
    doc = App.newDocument("slot_alignment_parallel")
    lines = lines_object(doc, "Parallel", [((0, 0, 0), (0, 0, 300)), ((60, 7, 0), (60, top_y, 300))])
    post = feature.make_profile("20-6", 2, 2, 100, doc, edge=(lines, "Edge1"))
    neighbour = feature.make_profile("20-6", 1, 2, 100, doc, edge=(lines, "Edge2"))
    doc.recompute()
    x_before = box_of(neighbour)[:2]
    result, _changed = align_picks(neighbour, "Right", 1, post, "Left", 1)
    doc.recompute()
    target_floor = floor_centre(neighbour, "Right", 1)
    reference_floor = floor_centre(post, "Left", 1)
    offset = feature.section_offset(neighbour)
    check(result == "moved" and abs(offset.x) < 1e-6 and abs(target_floor.y - reference_floor.y) < abs(top_y - 7) / 2 + 1e-3
          and abs(reference_floor.y + 10) < 1e-6,
          f"end y {top_y}: the neighbour's slot floor lines up with the post's across the face "
          f"({result}, offset {offset.x:.4f} {offset.y:.4f}, floors y {target_floor.y:.4f} "
          f"{reference_floor.y:.4f})")
    check(abs(box_of(neighbour)[0] - x_before[0]) < 1e-6 and abs(box_of(neighbour)[1] - x_before[1]) < 1e-6
          and neighbour.Shape.common(post.Shape).Volume < 1e-6,
          f"end y {top_y}: the neighbour does not slide onto the post ({box_of(neighbour)[:2]})")
    second, _changed = align_picks(neighbour, "Right", 1, post, "Left", 1)
    check(second == "unchanged", f"end y {top_y}: aligning again changes nothing ({second})")
    App.closeDocument(doc.Name)

# A section offset that moves a profile into a carriage's envelope reaches the carriage, through
# one carriage scan per recompute.
doc = App.newDocument("slot_alignment_carriage")
lines = lines_object(doc, "Carriage", [((0, 0, 0), (600, 0, 0)), ((300, -100, 60), (300, 100, 60))])
rail = feature.make_profile("20-6", 1, 1, 100, doc, edge=(lines, "Edge1"))
block = feature.make_profile("20-6", 1, 1, 100, doc, edge=(lines, "Edge2"))
doc.recompute()
car = linear.make_carriage(doc, rail, "Top", CarriageLength=60)
doc.recompute()
check(block.Name not in [o.Name for o in car.Neighbours], "the block starts clear of the carriage envelope")
frame = feature.member_frame(block)
dimension = "X" if abs(frame.x.z) > abs(frame.y.z) else "Y"
feature.ensure_section_offset_properties(block)
setattr(block, f"SectionOffset{dimension}", -35 / getattr(frame, dimension.lower()).z)  # bottom 50 -> 15
moved = []
original_member_moved = linear.member_moved
linear.member_moved = lambda member: (moved.append(member.Name), original_member_moved(member))
try:
    doc.recompute()
finally:
    linear.member_moved = original_member_moved
check(abs(block.Shape.BoundBox.ZMin - 15) < 1e-6 and block.Name in [o.Name for o in car.Neighbours],
      f"the shifted block reaches the carriage ({block.Shape.BoundBox.ZMin:.3f}, "
      f"{[o.Name for o in car.Neighbours]})")
check(moved.count(block.Name) == 1, f"one carriage scan for the shifted block per recompute ({moved})")
App.closeDocument(doc.Name)

print(f"{len(failures)} failure(s)")
sys.stdout.flush()
os._exit(1 if failures else 0)
