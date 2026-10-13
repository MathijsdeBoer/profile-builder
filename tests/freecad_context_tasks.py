"""Test which Tasks-tab command groups fit a selection, with FreeCAD's console."""

import os
import re
import sys

import freecad

ROOT = os.getcwd()
for _name in [m for m in sys.modules if m == "freecad.profile_builder" or m.startswith("freecad.profile_builder.")]:
    del sys.modules[_name]
freecad.__path__.insert(0, os.path.join(ROOT, "freecad"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402

from freecad.profile_builder import brackets, context_tasks, feature, joints, slot_alignment  # noqa: E402

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
create, align, join, parts, bracket_part, brackets_box, report = (w.title for w in context_tasks.watchers())

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

# The selection is read unresolved (getSelectionEx("", 0)), so picks come with their full subnames.
group = doc.addObject("App::DocumentObjectGroup", "Frame")
group.addObject(post)
doc.recompute()
check(shown([(group, (f"{post.Name}.{floor(post)}",)), (rail, (floor(rail),))]) == [align],
      "a slot floor on a profile inside a group counts as a slot floor")
check(shown([(group, (f"{post.Name}.",))]) == [join, parts], "a profile picked inside a group counts as a profile")

# Brackets: the two contact faces of the part offer Brackets and End plates, a Brackets object (or a
# face of one of its placed brackets) offers Calibrate bracket.
part = doc.addObject("Part::Feature", "BracketPart")
part.Shape = Part.makeBox(20, 20, 3).fuse(Part.makeBox(3, 20, 20)).removeSplitter()
placed = brackets.make_brackets(doc, part, made)
doc.recompute()
two_faces = [(part, ("Face1", "Face2"))]
summary = context_tasks.summarize(two_faces)
check((summary.part_faces, summary.parts, summary.other) == (2, 1, 0), f"faces on a part are counted ({summary})")
check(shown(two_faces) == [bracket_part],
      f"two faces on a bracket part offer the bracket commands ({shown(two_faces)})")
check(shown([(made[0], ("",))] + two_faces) == [bracket_part],
      "a joint and two faces on a bracket part offer only the bracket commands")
check(shown([(part, ("Face1",))]) == [create], "one face on a part offers no bracket commands yet")
other_part = doc.addObject("Part::Feature", "OtherPart")
other_part.Shape = Part.makeBox(10, 10, 10)
check(shown([(part, ("Face1",)), (other_part, ("Face1",))]) == [create],
      "faces on two different parts offer no bracket commands")
container = doc.addObject("App::Part", "Imported")
step_part = doc.addObject("Part::Feature", "StepBracket")
step_part.Shape = part.Shape.copy()
container.addObject(step_part)
doc.recompute()
step_pick = [(container, (f"{step_part.Name}.Face1", f"{step_part.Name}.Face2"))]
check(shown(step_pick) == [bracket_part],
      f"two faces on a part in an App::Part offer the bracket commands ({shown(step_pick)})")
check(shown([(placed, ("",))]) == [brackets_box],
      f"a Brackets object offers Calibrate bracket ({shown([(placed, ('',))])})")
calibration = [(placed, ("0.Face1", "0.Face2"))]
summary = context_tasks.summarize(calibration)
check((summary.brackets, summary.part_faces) == (1, 0), f"faces on a placed bracket count as its Brackets ({summary})")
check(shown(calibration) == [brackets_box],
      f"faces on a placed bracket offer Calibrate bracket ({shown(calibration)})")

empty_doc = App.newDocument("context_tasks_empty")
active = App.ActiveDocument
App.setActiveDocument(empty_doc.Name)
check(shown(EMPTY) == [create], f"a document without profiles does not offer the report ({shown(EMPTY)})")
App.setActiveDocument(active.Name)

# The watchers read the GUI selection through _picks. Replace it to drive them the way FreeCAD does,
# which asks all of them on every selection change, and count the work done.
all_watchers = context_tasks.watchers()
calls = {"summary": 0, "picked_slot": 0}
original_summary, original_picked = context_tasks._summary, slot_alignment.picked_slot


def ask_all(picks):
    original = context_tasks._picks
    context_tasks._picks = lambda: picks
    try:
        return [w.title for w in all_watchers if w.shouldShow()]
    finally:
        context_tasks._picks = original


def counted_summary(*args):
    calls["summary"] += 1
    return original_summary(*args)


def counted_picked(*args):
    calls["picked_slot"] += 1
    return original_picked(*args)


every = [f"Face{i}" for i in range(1, len(post.Shape.Faces) + 1)]
plain = [name for name in every if not context_tasks.summarize([(post, (name,))]).slots]
context_tasks._summary, slot_alignment.picked_slot = counted_summary, counted_picked
try:
    calls.update(summary=0, picked_slot=0)
    for count in range(1, len(plain) + 1):  # Ctrl+click the faces one after another
        result = ask_all([(post, tuple(plain[:count]))])
    check(calls["summary"] == len(plain),
          f"the selection is summarized once per change, not once per watcher ({calls['summary']} times for "
          f"{len(plain)} changes, {len(all_watchers)} watchers)")
    check(calls["picked_slot"] == len(plain),
          f"each face added to the selection is classified once ({calls['picked_slot']} for {len(plain)} faces)")
    check(result == [join, parts], f"{len(plain)} faces of a profile offer joints and parts ({result})")

    ask_all([])  # forget the faces classified so far
    calls.update(summary=0, picked_slot=0)
    result = ask_all([(post, tuple(every))])
    check(result == [], f"all faces of a profile, slot floors included, offer nothing ({result})")
    check(calls["picked_slot"] < len(every) // 4,
          f"classifying stops once the outcome is decided ({calls['picked_slot']} of {len(every)} faces)")

    ask_all([])
    calls.update(summary=0, picked_slot=0)
    ask_all([(post, (plain[0],))])
    ask_all([(post, (plain[0],))])
    post.ClosedLeft = not post.ClosedLeft
    doc.recompute()
    ask_all([(post, (plain[0],))])
    post.ClosedLeft = not post.ClosedLeft
    doc.recompute()
    check((calls["summary"], calls["picked_slot"]) == (2, 2),
          f"an unchanged selection is not summarized again, a recomputed profile is ({calls})")
finally:
    context_tasks._summary, slot_alignment.picked_slot = original_summary, original_picked

# Each command in a task box must be registered, or FreeCAD silently leaves its button out. The console
# cannot register commands, so look for the addCommand calls themselves.
commands = {name for w in context_tasks.watchers() for name in w.commands}
source = ""
for module in ("commands.py", "brackets_ui.py", "check_ui.py", "frame_ui.py", "linear_ui.py"):
    source += open(os.path.join(ROOT, "freecad", "profile_builder", module), encoding="utf-8").read()
registered = set(re.findall(r'addCommand\(\s*"([^"]+)"', source))
unknown = sorted(commands - registered)
check(not unknown, f"every command in a task box is registered ({unknown})")
check(len(registered) > 15 and "ProfileBuilder_CalibrateBracket" in registered,
      f"the registration check finds the addCommand calls ({len(registered)})")

# Qt shows a toolbar's name in the toolbar menu as action text, where "&" marks a shortcut letter.
gui_source = open(os.path.join(ROOT, "freecad", "profile_builder", "init_gui.py"), encoding="utf-8").read()
names = re.findall(r'QT_TRANSLATE_NOOP\("Workbench", "([^"]+)"\)', gui_source)
check(len(names) >= 4 and not [n for n in names if "&" in n], f"no toolbar or menu name contains '&' ({names})")

print(f"{len(failures)} failure(s)")
sys.stdout.flush()
os._exit(1 if failures else 0)
