"""Find profile spins and section offsets that line up slots at butt joints."""

from dataclasses import dataclass
import math

import FreeCAD as App

from . import brackets, feature, joints

translate = App.Qt.translate


@dataclass(frozen=True)
class Alignment:
    profile: object
    spin: float
    offset_x: float
    offset_y: float
    matches: int
    matched_joints: int
    eligible_joints: int
    current_spin: float
    current_offset_x: float
    current_offset_y: float
    slot_pair: object = None

    @property
    def changed(self):
        return (abs(_angle_delta(self.spin, self.current_spin)) > 1e-7
                or abs(self.offset_x - self.current_offset_x) > 1e-7
                or abs(self.offset_y - self.current_offset_y) > 1e-7)


@dataclass(frozen=True)
class _Connection:
    joint: object
    reference: object
    target_directions: tuple
    reference_directions: tuple
    reference_frame: object
    other_directions: tuple


@dataclass(frozen=True)
class _FaceGroup:
    joint_name: str
    reference_name: str
    dimension: str
    coefficient: float
    target_face: str
    reference_face: str
    target_slots: tuple
    reference_slots: tuple
    preference: float


@dataclass(frozen=True)
class SlotPair:
    joint_name: str
    reference_name: str
    spin: float
    target_face: str
    target_slot: int
    target_coordinate: float
    reference_face: str
    reference_slot: int
    reference_coordinate: float


@dataclass(frozen=True)
class PickedSlot:
    profile: object
    face: str
    slot: int


def direct_align_slots(target_slot, reference_slot, doc):
    """Directly align two picked slot floors without relying on joints.
    
    target_slot: the slot to align (on the profile to be adjusted)
    reference_slot: the reference slot (on the profile to stay fixed)
    doc: the FreeCAD document
    
    Returns: (list of Alignment objects, list of notes)
    """
    target_profile = target_slot.profile
    reference_profile = reference_slot.profile
    
    # Get frames for both profiles
    target_frame = feature.member_frame(target_profile)
    reference_frame = feature.member_frame(reference_profile)
    
    # Get slot floor centers in world coordinates
    target_info = _slot_floor_position(target_profile, target_frame, target_slot.face, target_slot.slot)
    reference_info = _slot_floor_position(reference_profile, reference_frame, reference_slot.face, reference_slot.slot)
    
    if target_info is None or reference_info is None:
        raise ValueError(f"Could not locate slot floor positions.")
    
    target_pos, target_normal = target_info
    reference_pos, reference_normal = reference_info
    
    # Compute offset from target slot to reference slot
    offset_world = reference_pos - target_pos
    
    # Project offset into target profile's local frame
    offset_x = offset_world.dot(target_frame.x)
    offset_y = offset_world.dot(target_frame.y)
    
    # Create alignment with no spin change, only offset
    current_offset = feature.section_offset(target_profile)
    alignment = Alignment(
        profile=target_profile,
        spin=target_profile.Spin.Value,  # No rotation
        offset_x=current_offset.x + offset_x,
        offset_y=current_offset.y + offset_y,
        matches=1,
        matched_joints=0,
        eligible_joints=0,
        current_spin=target_profile.Spin.Value,
        current_offset_x=current_offset.x,
        current_offset_y=current_offset.y,
        slot_pair=None
    )
    
    return [alignment], []


def _slot_floor_position(profile, frame, face_name, slot_index):
    """Get the world position of a slot floor center.
    
    Returns: (world_position_vector, face_normal) or None if not found
    """
    # Get the normal vector for this face
    face_data = {
        "Right": (frame.x, 1),
        "Left": (frame.x, -1),
        "Top": (frame.y, 1),
        "Bottom": (frame.y, -1),
    }
    
    if face_name not in face_data:
        return None
    
    axis, sign = face_data[face_name]
    normal = axis * sign
    across = frame.z  # perpendicular to face
    
    # Get slot positions from brackets
    slot_positions = brackets.face_slots(profile, frame, normal, across)
    if not slot_positions or len(slot_positions) < slot_index:
        return None
    
    # slot_positions is a list of positions along the perpendicular axis (in local coords)
    slot_coord_local = slot_positions[slot_index - 1]
    
    # Determine which axis (x or y) the perpendicular coordinate is along
    perp_axis = frame.y if face_name in ("Left", "Right") else frame.x
    
    # Compute slot floor center in world coordinates
    # The slot floor is at depth profile.SlotDepth.Value from the face
    depth_offset = profile.SlotDepth.Value * sign * -1
    world_pos = frame.origin + perp_axis * slot_coord_local + normal * depth_offset
    
    return (world_pos, normal)


def slot_pair_from_picks(target_slot, reference_slot):
    """Create a SlotPair from two PickedSlot selections.
    
    target_slot: the slot to align (on the profile to be adjusted)
    reference_slot: the reference slot (on the profile to stay fixed)
    
    Tries to find a pair in pre-computed joint candidates first,
    then returns None for arbitrary profile pairs (to be handled by direct_align_slots).
    """
    target_profile = target_slot.profile
    reference_profile = reference_slot.profile
    
    # Try to find a pair in pre-computed joint candidates
    all_choices = _slot_choices([target_profile, reference_profile])
    candidates = all_choices.get(target_profile.Name, [])
    
    for pair in candidates:
        if (pair.reference_name == reference_profile.Name and
            pair.target_face == target_slot.face and
            pair.target_slot == target_slot.slot and
            pair.reference_face == reference_slot.face and
            pair.reference_slot == reference_slot.slot):
            return pair
    
    # No pre-computed pair found. Return None to signal that direct_align_slots should be used.
    return None




def _angle_delta(first, second):
    return (first - second + 180.0) % 360.0 - 180.0


def _near_angle(angle, reference):
    return reference + _angle_delta(angle, reference)


def _directions_at(joint, profile, frame):
    directions = []
    for member, end in joints._live(joints.ends_of(joint)):
        if member.Name == profile.Name:
            directions.append(frame.z if end == "Start" else frame.z * -1)
    if any(member.Name == profile.Name for member in joints.passing_of(joint)):
        directions.extend((frame.z, frame.z * -1))
    return directions


def _connections(profile, targets):
    doc = profile.Document
    selected_names = {target.Name for target in targets}
    profile_frame = feature.member_frame(profile)
    found = []
    for joint in doc.Objects:
        if not joints.is_joint(joint) or joint.Type != "Butt":
            continue
        ends = joints._live(joints.ends_of(joint))
        members = list({member.Name: member for member, _end in ends + [
            (member, None) for member in joints.passing_of(joint)
        ]}.values())
        if profile.Name not in {member.Name for member in members}:
            continue
        target_directions = _directions_at(joint, profile, profile_frame)
        if not target_directions:
            continue
        references = [member for member in members
                      if member.Name not in selected_names and member.Name != profile.Name]
        for reference in references:
            reference_frame = feature.member_frame(reference)
            reference_directions = _directions_at(joint, reference, reference_frame)
            if reference_directions:
                other_directions = []
                for other in references:
                    if other.Name == reference.Name:
                        continue
                    other_frame = feature.member_frame(other)
                    other_directions.extend(_directions_at(joint, other, other_frame))
                found.append(_Connection(joint, reference, tuple(target_directions),
                                         tuple(reference_directions), reference_frame,
                                         tuple(other_directions)))
    return profile_frame, found


def _candidate_spins(frame, connections, current):
    values = [current]
    for connection in connections:
        for target_direction in connection.target_directions:
            for reference_direction in connection.reference_directions:
                if abs(target_direction.dot(reference_direction)) > joints.PERPENDICULAR:
                    continue
                desired = reference_direction - frame.z * reference_direction.dot(frame.z)
                if desired.Length < 1e-9:
                    continue
                desired.normalize()
                for axis in (frame.x, frame.x * -1, frame.y, frame.y * -1):
                    delta = math.degrees(math.atan2(frame.z.dot(axis.cross(desired)), axis.dot(desired)))
                    spin = _near_angle(current + delta, current)
                    if not any(abs(_angle_delta(spin, existing)) < 1e-6 for existing in values):
                        values.append(spin)
    return values


def _frame_at_spin(frame, spin, current):
    rotation = App.Rotation(frame.z, spin - current)
    return feature.Frame(frame.origin, rotation.multVec(frame.x), rotation.multVec(frame.y), frame.z, frame.rect)


def _canonical_across(across):
    for component in (across.x, across.y, across.z):
        if abs(component) > 1e-9:
            return across if component > 0 else across * -1
    return across


def _face_name(frame, normal):
    for name, axis, sign in brackets.FACE_AXES:
        if (getattr(frame, axis) * sign).dot(normal) > joints.PARALLEL:
            return name
    return None


def _face_slots(obj, frame, face, normal, across):
    slots = brackets.face_slots(obj, frame, normal, across)
    if slots is None or not slots:
        return ()
    axis = next(axis for name, axis, _sign in brackets.FACE_AXES if name == face)
    if axis == "y":
        start, count = frame.rect[0], obj.Columns
    else:
        start, count = frame.rect[2], obj.Rows
    cell = obj.CellSize.Value
    return tuple((index + 1, position, start + (index + 0.5) * cell)
                 for index, position in enumerate(slots[:count]))


def picked_slot(obj, subelement):
    """Describe a selected planar slot floor by its profile face and slot number."""
    def invalid():
        return ValueError(translate("ProfileBuilder", "{profile}: {subelement} is not a slot floor. "
                                    "Select the flat bottom of an open slot.")
                          .format(profile=obj.Label, subelement=subelement))

    if not feature.is_profile(obj) or not subelement.startswith("Face") or not subelement[4:].isdigit():
        raise invalid()
    index = int(subelement[4:]) - 1
    faces = obj.Shape.Faces
    if index < 0 or index >= len(faces):
        raise invalid()
    face = faces[index]
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


def _face_groups(profile, frame, connections):
    groups = []
    for connection in connections:
        for target_direction in connection.target_directions:
            for reference_direction in connection.reference_directions:
                if abs(target_direction.dot(reference_direction)) > joints.PERPENDICULAR:
                    continue
                across = target_direction.cross(reference_direction)
                if across.Length < 1e-9:
                    continue
                across.normalize()
                across = _canonical_across(across)
                target_slots = brackets.face_slots(profile, frame, reference_direction, across)
                reference_slots = brackets.face_slots(connection.reference, connection.reference_frame,
                                                      target_direction, across)
                if target_slots is None or reference_slots is None or not target_slots or not reference_slots:
                    continue
                x = frame.x.dot(across)
                y = frame.y.dot(across)
                if abs(x) >= abs(y):
                    dimension, coefficient = "x", x
                else:
                    dimension, coefficient = "y", y
                if abs(coefficient) < 0.95:
                    continue
                target_face = _face_name(frame, reference_direction)
                reference_face = _face_name(connection.reference_frame, target_direction)
                if target_face is None or reference_face is None:
                    continue
                target_slots = _face_slots(profile, frame, target_face, reference_direction, across)
                reference_slots = _face_slots(connection.reference, connection.reference_frame,
                                               reference_face, target_direction, across)
                if not target_slots or not reference_slots:
                    continue
                preference = sum(direction.dot(across) for direction in connection.other_directions)
                groups.append(_FaceGroup(connection.joint.Name, connection.reference.Name, dimension, coefficient,
                                         target_face, reference_face, target_slots, reference_slots, preference))
    return groups


def _matches(group, coordinate, current):
    shift = group.coefficient * (coordinate - current)
    return sum(abs(target + shift - reference) <= brackets.SLOT_TOLERANCE
               for _target_index, target, _target_local in group.target_slots
               for _reference_index, reference, _reference_local in group.reference_slots)


def _best_coordinates(groups, dimension, current):
    relevant = [group for group in groups if group.dimension == dimension]
    if not relevant:
        return [current]

    centers = {round(current + (reference[1] - target[1]) / group.coefficient, 9)
               for group in relevant for target in group.target_slots for reference in group.reference_slots}
    candidates = centers | {current}
    ordered = sorted(centers)
    for i, first in enumerate(ordered):
        for second in ordered[i + 1:]:
            if second - first > 2 * brackets.SLOT_TOLERANCE + 1e-9:
                break
            candidates.add((first + second) / 2)

    scores = {
        coordinate: sum(_matches(group, coordinate, current) for group in relevant)
        for coordinate in candidates
    }
    best_score = max(scores.values())
    best = [coordinate for coordinate, score in scores.items() if score == best_score]
    movement = min(abs(coordinate - current) for coordinate in best)
    return [coordinate for coordinate in best if abs(abs(coordinate - current) - movement) < 1e-7]


def _score(groups, offset_x, offset_y, current_x, current_y):
    matched_joints = set()
    matches = 0
    for group in groups:
        coordinate = offset_x if group.dimension == "x" else offset_y
        current = current_x if group.dimension == "x" else current_y
        count = _matches(group, coordinate, current)
        matches += count
        if count:
            matched_joints.add(group.joint_name)
    return matches, len(matched_joints)


def _best_alignment(profile, targets, slot_pair=None):
    current_spin = profile.Spin.Value
    offset = feature.section_offset(profile)
    current_x, current_y = offset.x, offset.y
    base_frame, connections = _connections(profile, targets)
    if not connections:
        return None

    best = None
    for spin in _candidate_spins(base_frame, connections, current_spin):
        if slot_pair is not None and abs(_angle_delta(spin, slot_pair.spin)) > 1e-6:
            continue
        frame = _frame_at_spin(base_frame, spin, current_spin)
        groups = _face_groups(profile, frame, connections)
        if not groups:
            continue
        if slot_pair is None:
            coordinate_pairs = [(_best_coordinates(groups, "x", current_x),
                                 _best_coordinates(groups, "y", current_y))]
        else:
            anchor_groups = [group for group in groups
                             if group.joint_name == slot_pair.joint_name
                             and group.reference_name == slot_pair.reference_name
                             and group.target_face == slot_pair.target_face
                             and group.reference_face == slot_pair.reference_face]
            coordinate_pairs = []
            for group in anchor_groups:
                targets = [item for item in group.target_slots if item[0] == slot_pair.target_slot]
                references = [item for item in group.reference_slots if item[0] == slot_pair.reference_slot]
                for _target_index, target, _target_local in targets:
                    for _reference_index, reference, _reference_local in references:
                        coordinate = current_x if group.dimension == "x" else current_y
                        forced = coordinate + (reference - target) / group.coefficient
                        xs = ([forced] if group.dimension == "x"
                              else _best_coordinates(groups, "x", current_x))
                        ys = ([forced] if group.dimension == "y"
                              else _best_coordinates(groups, "y", current_y))
                        coordinate_pairs.append((xs, ys))
            if not coordinate_pairs:
                continue
        old_center = base_frame.center_offset()
        for xs, ys in coordinate_pairs:
            for offset_x in xs:
                for offset_y in ys:
                    matches, matched_joints = _score(groups, offset_x, offset_y, current_x, current_y)
                    center = frame.center_offset()
                    movement = math.hypot(offset_x - current_x, offset_y - current_y)
                    spin_change = abs(_angle_delta(spin, current_spin))
                    shift = center - old_center
                    preference = sum(
                        group.preference * group.coefficient *
                        ((offset_x if group.dimension == "x" else offset_y)
                         - (current_x if group.dimension == "x" else current_y))
                        for group in groups
                        if group.preference and _matches(
                            group,
                            offset_x if group.dimension == "x" else offset_y,
                            current_x if group.dimension == "x" else current_y)
                    )
                    key = (matches, matched_joints, -movement, -spin_change, preference,
                           shift.x, shift.y, shift.z, -spin)
                    if best is None or key > best[0]:
                        best = (key, spin, offset_x, offset_y, matches, matched_joints,
                                len({group.joint_name for group in groups}), slot_pair)
    if best is None or best[4] == 0:
        return None
    _key, spin, offset_x, offset_y, matches, matched_joints, eligible_joints, slot_pair = best
    return Alignment(profile, spin, offset_x, offset_y, matches, matched_joints, eligible_joints,
                     current_spin, current_x, current_y, slot_pair)


def slot_choices(profiles):
    """Return all specific slot pairs available for each selected profile."""
    return _slot_choices(profiles)


def slot_pairs_for_picked_slots(profiles, picked_slots):
    """Return target-slot candidates anchored to the picked reference slot floors."""
    references = {(slot.profile.Name, slot.face, slot.slot) for slot in picked_slots}
    return _slot_choices(profiles, references)


def _slot_choices(profiles, reference_slots=None):
    targets = list({profile.Name: profile for profile in profiles if feature.is_profile(profile)}.values())
    choices = {}
    for profile in targets:
        pairs = {}
        if not profile.PathEdge:
            choices[profile.Name] = []
            continue
        try:
            feature.path_edge(profile)
            frame, connections = _connections(profile, targets)
        except ValueError:
            choices[profile.Name] = []
            continue
        for spin in _candidate_spins(frame, connections, profile.Spin.Value):
            turned = _frame_at_spin(frame, spin, profile.Spin.Value)
            for group in _face_groups(profile, turned, connections):
                for target_slot, _target_position, target_coordinate in group.target_slots:
                    for reference_slot, _reference_position, reference_coordinate in group.reference_slots:
                        if (reference_slots is not None
                                and (group.reference_name, group.reference_face, reference_slot) not in reference_slots):
                            continue
                        pair = SlotPair(group.joint_name, group.reference_name, spin, group.target_face,
                                        target_slot, target_coordinate, group.reference_face, reference_slot,
                                        reference_coordinate)
                        key = (pair.joint_name, pair.reference_name, round(pair.spin, 6), pair.target_face,
                               pair.target_slot, pair.reference_face, pair.reference_slot)
                        pairs[key] = pair
        choices[profile.Name] = sorted(
            pairs.values(),
            key=lambda pair: (pair.joint_name, pair.reference_name, pair.reference_face,
                              pair.reference_slot, pair.target_face, pair.target_slot, pair.spin))
    return choices


def _picked_slot_coverage(profile, targets, alignment, candidates):
    references = {(pair.reference_name, pair.reference_face, pair.reference_slot) for pair in candidates}
    if len(references) <= 1:
        return len(references)

    current = feature.section_offset(profile)
    base_frame, connections = _connections(profile, targets)
    frame = _frame_at_spin(base_frame, alignment.spin, profile.Spin.Value)
    groups = _face_groups(profile, frame, connections)
    hits = set()
    for group in groups:
        coordinate = alignment.offset_x if group.dimension == "x" else alignment.offset_y
        baseline = current.x if group.dimension == "x" else current.y
        shift = group.coefficient * (coordinate - baseline)
        for reference in references:
            if (group.reference_name, group.reference_face) != reference[:2]:
                continue
            reference_positions = [position for index, position, _local in group.reference_slots
                                   if index == reference[2]]
            for position in reference_positions:
                if any(abs(target + shift - position) <= brackets.SLOT_TOLERANCE
                       for _index, target, _local in group.target_slots):
                    hits.add(reference)
                    break
    return len(hits)


def plan(profiles, slot_pairs=None):
    """Plan alignments for selected profiles, using unselected butt-jointed members as references."""
    targets = list({profile.Name: profile for profile in profiles if feature.is_profile(profile)}.values())
    if not targets:
        return [], [translate("ProfileBuilder", "Select the profile or profiles whose slots should be aligned.")]
    alignments, notes = [], []
    for profile in targets:
        if not profile.PathEdge:
            notes.append(translate("ProfileBuilder", "{profile} does not follow a sketch edge, so its slots "
                                   "cannot be aligned at joints").format(profile=profile.Label))
            continue
        try:
            feature.path_edge(profile)
            if slot_pairs is None:
                alignment = _best_alignment(profile, targets)
                candidates = ()
            else:
                candidates = slot_pairs.get(profile.Name, ())
                if isinstance(candidates, SlotPair):
                    candidates = (candidates,)
                else:
                    candidates = tuple(candidates)
                if not candidates:
                    notes.append(translate("ProfileBuilder", "{profile} has no selected reference slot at an "
                                           "applicable butt joint").format(profile=profile.Label))
                    continue
                options = []
                for pair in candidates:
                    proposed = _best_alignment(profile, targets, pair)
                    if proposed is None:
                        continue
                    coverage = _picked_slot_coverage(profile, targets, proposed, candidates)
                    movement = math.hypot(proposed.offset_x - proposed.current_offset_x,
                                          proposed.offset_y - proposed.current_offset_y)
                    spin_change = abs(_angle_delta(proposed.spin, proposed.current_spin))
                    options.append(((coverage, proposed.matches, proposed.matched_joints,
                                     -movement, -spin_change, -proposed.spin), proposed))
                alignment = max(options, key=lambda item: item[0])[1] if options else None
        except ValueError as error:
            notes.append(str(error))
            continue
        if alignment is None:
            text = ("{profile} cannot align any selected reference slot at the current butt joints"
                    if slot_pairs is not None else
                    "{profile} has no open, perpendicular slot faces to align with an unselected profile "
                    "at a butt joint")
            notes.append(translate("ProfileBuilder", text).format(profile=profile.Label))
            continue
        alignments.append(alignment)
        if candidates:
            coverage = _picked_slot_coverage(profile, targets, alignment, candidates)
            selected = len({(pair.reference_name, pair.reference_face, pair.reference_slot)
                            for pair in candidates})
            if coverage < selected:
                notes.append(translate("ProfileBuilder", "{profile}: only {matched} of {selected} selected "
                                       "reference slots can be lined up").format(profile=profile.Label,
                                                                                 matched=coverage,
                                                                                 selected=selected))
        if alignment.matched_joints < alignment.eligible_joints:
            notes.append(translate("ProfileBuilder", "{profile}: slots align at {matched} of {eligible} applicable "
                                   "butt joints").format(profile=profile.Label,
                                                         matched=alignment.matched_joints,
                                                         eligible=alignment.eligible_joints))
    return alignments, notes


def apply(doc, alignments):
    """Apply planned section spins and offsets in one undoable document transaction."""
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
