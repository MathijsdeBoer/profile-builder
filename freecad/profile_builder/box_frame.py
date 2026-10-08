"""Create a cube frame from a parametric wire skeleton."""

from . import feature, joints, profiles
from . import skeleton as skeleton_module


def _validate_size(series, columns, rows, label):
    if series not in profiles.SERIES:
        raise ValueError(f"Unknown {label} series: {series}")
    if (columns, rows) not in profiles.SERIES[series].sizes \
            and (rows, columns) not in profiles.SERIES[series].sizes:
        raise ValueError(f"Unsupported {label} size: {columns}x{rows} ({series})")


def make_box(doc, width=600.0, depth=600.0, height=700.0, size_mode="Outside",
             post_series=profiles.DEFAULT_SERIES, post_cols=1, post_rows=1,
             rail_series=profiles.DEFAULT_SERIES, rail_cols=1, rail_rows=1,
             post_weight="Standard", rail_weight="Standard", slot_style="T-slot"):
    """Create a skeleton, eight rails, four posts and their vertical butt joints."""
    _validate_size(post_series, post_cols, post_rows, "post")
    _validate_size(rail_series, rail_cols, rail_rows, "rail")
    if post_weight not in profiles.WEIGHTS or rail_weight not in profiles.WEIGHTS:
        raise ValueError("Unknown profile weight class")
    if slot_style not in profiles.SLOT_STYLES:
        raise ValueError(f"Unknown slot style: {slot_style}")

    post_cell = profiles.SERIES[post_series].cell
    rail_cell = profiles.SERIES[rail_series].cell
    post_width, post_depth = post_cols * post_cell, post_rows * post_cell
    rail_width, rail_height = rail_cols * rail_cell, rail_rows * rail_cell
    if skeleton_module.rails_collide(post_width, post_depth, rail_width):
        raise ValueError("Rails wider than the posts in both directions collide at the corners: "
                         "use posts at least as wide as the rails in one direction, or narrower rails")
    skeleton_module.centerline_spans(width, depth, height, size_mode, skeleton_module.uniform_sides(
        post_width, post_depth, rail_width, rail_height))

    skeleton = skeleton_module.make_skeleton(
        doc, width, depth, height, size_mode,
        post_width, post_depth, rail_width, rail_height)
    members = []
    for edge in range(1, 13):
        if edge <= 8:
            series, cols, rows, weight, role = (
                rail_series, rail_cols, rail_rows, rail_weight, "Butts")
        else:
            series, cols, rows, weight, role = (
                post_series, post_cols, post_rows, post_weight, "Runs through")
        members.append(feature.make_profile(
            series, cols, rows, 1000.0, doc, edge=(skeleton, f"Edge{edge}"),
            Weight=weight, SlotStyle=slot_style, Anchor="Center", JointRole=role))

    doc.recompute()
    warnings = []
    created_joints = joints.create_joints(doc, members, "Butt", "Vertical", warnings=warnings)
    doc.recompute()
    return skeleton, members, created_joints, warnings
