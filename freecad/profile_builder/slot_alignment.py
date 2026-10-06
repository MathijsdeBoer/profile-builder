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
    dimension: str
    coefficient: float
    target_slots: tuple
    reference_slots: tuple
    preference: float


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
                preference = sum(direction.dot(across) for direction in connection.other_directions)
                groups.append(_FaceGroup(connection.joint.Name, dimension, coefficient,
                                         tuple(target_slots), tuple(reference_slots), preference))
    return groups


def _matches(group, coordinate, current):
    shift = group.coefficient * (coordinate - current)
    return sum(abs(target + shift - reference) <= brackets.SLOT_TOLERANCE
               for target in group.target_slots for reference in group.reference_slots)


def _best_coordinates(groups, dimension, current):
    relevant = [group for group in groups if group.dimension == dimension]
    if not relevant:
        return [current]

    centers = {round(current + (reference - target) / group.coefficient, 9)
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


def _best_alignment(profile, targets):
    current_spin = profile.Spin.Value
    offset = feature.section_offset(profile)
    current_x, current_y = offset.x, offset.y
    base_frame, connections = _connections(profile, targets)
    if not connections:
        return None

    best = None
    for spin in _candidate_spins(base_frame, connections, current_spin):
        frame = _frame_at_spin(base_frame, spin, current_spin)
        groups = _face_groups(profile, frame, connections)
        if not groups:
            continue
        xs = _best_coordinates(groups, "x", current_x)
        ys = _best_coordinates(groups, "y", current_y)
        old_center = base_frame.center_offset()
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
                            len({group.joint_name for group in groups}))
    if best is None or best[4] == 0:
        return None
    _key, spin, offset_x, offset_y, matches, matched_joints, eligible_joints = best
    return Alignment(profile, spin, offset_x, offset_y, matches, matched_joints, eligible_joints,
                     current_spin, current_x, current_y)


def plan(profiles):
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
            alignment = _best_alignment(profile, targets)
        except ValueError as error:
            notes.append(str(error))
            continue
        if alignment is None:
            notes.append(translate("ProfileBuilder", "{profile} has no open, perpendicular slot faces to align with "
                                   "an unselected profile at a butt joint").format(profile=profile.Label))
            continue
        alignments.append(alignment)
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
