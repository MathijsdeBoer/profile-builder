"""Test which Tasks-tab command groups fit a selection, with FreeCAD's console."""

import os
import sys

import freecad

ROOT = os.getcwd()
for _name in [m for m in sys.modules if m == "freecad.profile_builder" or m.startswith("freecad.profile_builder.")]:
    del sys.modules[_name]
freecad.__path__.insert(0, os.path.join(ROOT, "freecad"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402

from freecad.profile_builder import context_tasks, feature, joints, slot_alignment  # noqa: E402

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
doc = App.newDocument("context_tasks")
lines = doc.addObject("Part::Feature", "Loose")
lines.Shape = Part.makeCompound([Part.makeLine(V(0, 0, 0), V(0, 0, 300)),
                                  Part.makeLine(V(0, 0, 300), V(200, 0, 300))])
post = feature.make_profile("20-6", 2, 2, 100, doc, edge=(lines, "Edge1"))
rail = feature.make_profile("20-6", 1, 2, 100, doc, edge=(lines, "Edge2"))
doc.recompute()
made = joints.create_joints(doc, (rail, post), "Butt", "Longest")
doc.recompute()


def floor(profile):
    for index in range(1, len(profile.Shape.Faces) + 1):
        try:
            slot_alignment.picked_slot(profile, f"Face{index}")
        except ValueError:
            continue
        return f"Face{index}"
    raise AssertionError(f"no slot floor on {profile.Label}")


def non_slot_face(profile):
    for index in range(1, len(profile.Shape.Faces) + 1):
        try:
            slot_alignment.picked_slot(profile, f"Face{index}")
        except ValueError:
            return f"Face{index}"
    raise AssertionError("every face is a slot floor")


def shown(selection):
    """Titles of the watchers that would show for a selection, by patching the selection they read."""
    summary = context_tasks.summarize(selection)
    original = context_tasks.current_selection
    context_tasks.current_selection = lambda: summary
    try:
        return [w.title for w in context_tasks.watchers() if w.shouldShow()]
    finally:
        context_tasks.current_selection = original


EMPTY = ()
create, align, join, parts, brackets_box, report = (w.title for w in context_tasks.watchers())

check(shown(EMPTY) == [create, report], f"nothing selected offers create and report ({shown(EMPTY)})")
check(shown([(lines, ("",))]) == [create], f"a sketch alone offers only create ({shown([(lines, ('',))])})")
check(shown([(post, ("",))]) == [join, parts], f"a profile offers joints and parts ({shown([(post, ('',))])})")
check(shown([(post, (non_slot_face(post),))]) == [join, parts],
      "clicking a profile's own face counts as selecting the profile")
check(shown([(made[0], ("",))]) == [join, parts], "a joint offers joints and parts")
check(shown([(post, (floor(post),)), (rail, (floor(rail),))]) == [align],
      "two slot floors offer only the slot alignment")
check(shown([(post, (floor(post),))]) == [], "one slot floor offers nothing yet")
check(shown([(post, (floor(post),)), (rail, (floor(rail),)), (post, ("",))]) == [],
      "slot floors mixed with a whole profile offer nothing")

summary = context_tasks.summarize([(post, ("",)), (rail, ("",)), (lines, ("",))])
check((summary.profiles, summary.joints, summary.other, summary.total) == (2, 0, 1, 3),
      f"the selection is counted by kind ({summary})")

empty_doc = App.newDocument("context_tasks_empty")
active = App.ActiveDocument
App.setActiveDocument(empty_doc.Name)
check(shown(EMPTY) == [create], f"a document without profiles does not offer the report ({shown(EMPTY)})")
App.setActiveDocument(active.Name)

commands = {name for w in context_tasks.watchers() for name in w.commands}
source = open(os.path.join(ROOT, "freecad", "profile_builder", "commands.py"), encoding="utf-8").read()
source += open(os.path.join(ROOT, "freecad", "profile_builder", "brackets_ui.py"), encoding="utf-8").read()
source += open(os.path.join(ROOT, "freecad", "profile_builder", "check_ui.py"), encoding="utf-8").read()
source += open(os.path.join(ROOT, "freecad", "profile_builder", "frame_ui.py"), encoding="utf-8").read()
source += open(os.path.join(ROOT, "freecad", "profile_builder", "linear_ui.py"), encoding="utf-8").read()
unknown = sorted(name for name in commands if f'"{name}"' not in source)
check(not unknown, f"every command in a task box is registered ({unknown})")

print(f"{len(failures)} failure(s)")
sys.stdout.flush()
os._exit(1 if failures else 0)
