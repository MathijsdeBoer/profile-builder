"""Line up a picked slot on one profile with a picked slot on another by shifting its section."""

from dataclasses import dataclass

import FreeCAD as App

from . import brackets, check, feature, joints

translate = App.Qt.translate


@dataclass(frozen=True)
class Alignment:
    profile: object
    spin: float
    offset_x: float
    offset_y: float
    current_spin: float
    current_offset_x: float
    current_offset_y: float

    @property
    def changed(self):
        return (abs(_angle_delta(self.spin, self.current_spin)) > 1e-7
                or abs(self.offset_x - self.current_offset_x) > 1e-7
                or abs(self.offset_y - self.current_offset_y) > 1e-7)


@dataclass(frozen=True)
class PickedSlot:
    profile: object
    face: str
    slot: int


def _face_along(frame, face):
    """The direction in which the slots of ``face`` sit side by side."""
    return frame.y if face in ("Left", "Right") else frame.x


def _slot_center(profile, frame, face, slot):
    """World position of the centre line of slot ``slot`` (1-based) on ``face``, on the profile axis plane."""
    if face in ("Left", "Right"):
        along, start, count = frame.y, frame.rect[2], profile.Rows
    else:
        along, start, count = frame.x, frame.rect[0], profile.Columns
    if not 1 <= slot <= count:
        raise ValueError(translate("ProfileBuilder", "{profile} has no slot {slot} on its {face} face")
                         .format(profile=profile.Label, slot=slot, face=face))
    return frame.origin + along * (start + (slot - 0.5) * profile.CellSize.Value)


def _face_normal(frame, face):
    for name, axis, sign in brackets.FACE_AXES:
        if name == face:
            return getattr(frame, axis) * sign
    raise ValueError(face)


def direct_align_slots(target_slot, reference_slot):
    """Slide the target profile along its section so its picked slot lines up with the reference slot.

    The slots are lined up across both profile axes (their cross product), the way two slots meet at
    a butt joint. Parallel (or nearly parallel) profiles are lined up across the target face's
    normal instead. Picks whose slots cannot line up that way are refused: a turned profile, a face
    that points along the alignment direction, or a slide that would push the target into the
    reference. The target keeps its spin and its sketch edge;
    only its section offset changes.
    """
    target, reference = target_slot.profile, reference_slot.profile
    target_frame = feature.member_frame(target)
    reference_frame = feature.member_frame(reference)

    # Nearly parallel profiles (as joints count them) have no useful cross
    # product: it can point from one profile to the other.
    if abs(target_frame.z.dot(reference_frame.z)) > joints.PARALLEL:
        across = target_frame.z.cross(_face_normal(target_frame, target_slot.face))
    else:
        across = target_frame.z.cross(reference_frame.z)
    across.normalize()

    along_x = target_frame.x.dot(across)
    along_y = target_frame.y.dot(across)
    if abs(along_x) >= abs(along_y):
        dimension, coefficient = "x", along_x
    else:
        dimension, coefficient = "y", along_y
    if abs(coefficient) < joints.PARALLEL:
        raise ValueError(translate(
            "ProfileBuilder", "{target} is turned (Spin) so the slots cannot be lined up by sliding it; "
            "set its Spin so its faces are square to {reference} first.")
            .format(target=target.Label, reference=reference.Label))
    if max(abs(reference_frame.x.dot(across)), abs(reference_frame.y.dot(across))) < joints.PARALLEL:
        raise ValueError(translate(
            "ProfileBuilder", "{reference} is turned (Spin) so its slots cannot be lined up with {target}; "
            "set its Spin so its faces are square to {target} first.")
            .format(target=target.Label, reference=reference.Label))
    # The slots of a face sit side by side along it. On a face that points
    # along ``across`` they are all at the same distance, and sliding the
    # target would never line them up.
    for picked, frame, other in ((target_slot, target_frame, reference),
                                 (reference_slot, reference_frame, target)):
        if abs(_face_along(frame, picked.face).dot(across)) < joints.PARALLEL:
            raise ValueError(translate(
                "ProfileBuilder", "The slots on the {face} face of {profile} cannot be lined up with "
                "{other}: that face points the way the slots would slide. Pick a slot on a face next to it.")
                .format(face=picked.face, profile=picked.profile.Label, other=other.Label))

    gap = (_slot_center(reference, reference_frame, reference_slot.face, reference_slot.slot)
           - _slot_center(target, target_frame, target_slot.face, target_slot.slot)).dot(across)
    shift = (target_frame.x if dimension == "x" else target_frame.y) * (gap / coefficient)
    if shift.Length > 1e-7 and _pushes_into(target, reference, shift):
        raise ValueError(translate(
            "ProfileBuilder", "Lining up these slots would push {target} into {reference}: {reference} sits "
            "beside it in the direction the slots would slide.")
            .format(target=target.Label, reference=reference.Label))
    current = feature.section_offset(target)
    offset_x = current.x + (gap / coefficient if dimension == "x" else 0.0)
    offset_y = current.y + (gap / coefficient if dimension == "y" else 0.0)
    spin = target.Spin.Value
    return [Alignment(target, spin, offset_x, offset_y, spin, current.x, current.y)]


def _pushes_into(target, reference, shift):
    """Whether moving ``target`` by ``shift`` makes it overlap ``reference`` more than it does now.

    Profiles side by side along the slide direction (parallel ones picked on
    faces that look the same way, or skewed ones) would end up inside each
    other. Overlap that is already there, at an unjoined corner, is left alone.
    """
    target_box, reference_box = check._envelope(target), check._envelope(reference)
    moved = target_box.translated(shift)
    if not moved.BoundBox.intersect(reference_box.BoundBox):
        return False
    before = target_box.common(reference_box).Volume
    return moved.common(reference_box).Volume > before + check.CLASH_VOLUME


def _angle_delta(first, second):
    return (first - second + 180.0) % 360.0 - 180.0


def _face_name(frame, normal):
    for name, axis, sign in brackets.FACE_AXES:
        if (getattr(frame, axis) * sign).dot(normal) > joints.PARALLEL:
            return name
    return None


def picked_slot(obj, subelement):
    """Describe a selected planar slot floor by its profile face and slot number."""
    def invalid():
        return ValueError(translate("ProfileBuilder", "{profile}: {subelement} is not a slot floor. "
                                    "Select the flat bottom of an open slot.")
                          .format(profile=obj.Label, subelement=subelement))

    if not feature.is_profile(obj) or not subelement.startswith("Face") or not subelement[4:].isdigit():
        raise invalid()
    try:
        face = obj.Shape.getElement(subelement)  # IndexError past the last face, ValueError for Face0
    except Exception:
        raise invalid() from None
    surface = face.Surface
    if type(surface).__name__ != "Plane":
        raise invalid()

    frame = feature.member_frame(obj)
    world_center = face.CenterOfMass
    u, v = surface.parameter(world_center)
    normal = face.normalAt(u, v)
    side = _face_name(frame, normal)
    if side is None or getattr(obj, f"Closed{side}"):
        raise invalid()

    axis = frame.x if side in ("Left", "Right") else frame.y
    if side in ("Right", "Top"):
        boundary = frame.rect[1] if side == "Right" else frame.rect[3]
        expected = boundary - obj.SlotDepth.Value
    else:
        boundary = frame.rect[0] if side == "Left" else frame.rect[2]
        expected = boundary + obj.SlotDepth.Value
    tolerance = max(0.02, obj.CellSize.Value * 1e-5)
    coordinate = (world_center - frame.origin).dot(axis)
    if abs(coordinate - expected) > tolerance:
        raise invalid()

    along = frame.y if side in ("Left", "Right") else frame.x
    start, count = ((frame.rect[2], obj.Rows) if side in ("Left", "Right")
                    else (frame.rect[0], obj.Columns))
    slot_coordinates = [(vertex.Point - frame.origin).dot(along) for vertex in face.Vertexes]
    if not slot_coordinates:
        raise invalid()
    low, high = min(slot_coordinates) - tolerance, max(slot_coordinates) + tolerance
    slot_centers = [start + (index + 0.5) * obj.CellSize.Value for index in range(count)]
    matching_slots = [index for index, center in enumerate(slot_centers)
                      if low <= center <= high]
    if len(matching_slots) != 1:
        raise invalid()
    return PickedSlot(obj, side, matching_slots[0] + 1)


def apply(doc, alignments):
    """Apply the alignments' section spins and offsets in one undoable document transaction."""
    changed = [alignment for alignment in alignments if alignment.changed]
    if not changed:
        return []
    doc.openTransaction("Align slots")
    try:
        for alignment in changed:
            profile = alignment.profile
            if ("SectionOffsetX" in profile.PropertiesList or "SectionOffsetY" in profile.PropertiesList
                    or abs(alignment.offset_x) > 1e-7 or abs(alignment.offset_y) > 1e-7):
                feature.ensure_section_offset_properties(profile)
                profile.SectionOffsetX = alignment.offset_x
                profile.SectionOffsetY = alignment.offset_y
            profile.Spin = alignment.spin
        doc.recompute()
        invalid = [alignment.profile.Label for alignment in changed
                   if alignment.profile.Shape.isNull() or not alignment.profile.Shape.isValid()]
        if invalid:
            raise RuntimeError(translate("ProfileBuilder", "Slot alignment did not produce valid profiles: "
                                         "{profiles}").format(profiles=", ".join(invalid)))
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    return changed
