# AI disclosure

Most of this project was written by an AI model. This file describes which model, how it was used,
and what that means for the code.

## Model and tool

| | |
|---|---|
| Model | Claude Opus 5.5, by Anthropic |
| Model ID | `claude-opus-5-5` |
| Tool | Claude Code, in the Code tab of the Claude desktop app (Windows 11) |
| Human | Mathijs de Boer: direction, requirements, testing and review in FreeCAD |

The model worked as a coding agent in this repository. It wrote files, ran the tests, and ran FreeCAD
1.1 (both `freecadcmd` and the GUI, driven by test scripts) to check its own work. Commits it created
carry a `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` trailer.

## Timeline

All work was done in one Claude Code session. On 2026-09-28 the session also ran Claude Code workflows,
which spread work over several subagents of the same model.

| Date | Work | Commit |
|---|---|---|
| 2026-09-24 | The initial workbench: profile catalog and geometry, parametric profile object, task panel, quick-insert commands, cut list, generated icons, tests. | |
| 2026-09-24 | Joints (butt, miter, T-junctions), sheet panels, pricing with delivery and tax, stock bar optimisation, cost report. | |
| 2026-09-24 | Control over which profile runs through a butt joint (`JointRole`, **Run through**, **Swap joint**), after a problem found in manual testing. | `8733122` |
| 2026-09-25 | Slot systems (B-type, I-type, Misumi), I-type series, weight classes (Standard, Light, Ultralight, Heavy). | `a238935` |
| 2026-09-25 | This disclosure. | `f4d8bfe` |
| 2026-09-25 | `CLAUDE.md` guidance for future AI sessions. | `ead3f7d` |
| 2026-09-28 | Feature brainstorm as a multi-agent Claude Code workflow: 6 idea agents, 1 merge agent, 3 agents checking the ideas against the code. The result is `docs/plans/`. | |
| 2026-09-28 | Fixes for bugs found by that check, and the quick wins: section properties, section cache, panel materials and thermal fit, piece marks, a CSV variant with decimal commas. | `46a7734` |
| 2026-09-28 | An adversarial review of those changes as a second workflow: 5 reviewers, then one verifier per finding, which had to reproduce the finding in FreeCAD. The 21 confirmed defects were fixed, each with a regression test, and a document saved by the previous version was added as a test fixture. | `46a7734` |
| 2026-09-29 | The backward-compatibility fixtures had been saved by the new code (FreeCAD loaded the workbench from the main checkout through its Mod link), so the tests loading old documents had not tested old documents. The fixtures were rebuilt from worktrees of the old commits, and the test scripts now check which copy they load. | `678c9b7` |
| 2026-09-29 | Removal of regional assumptions that had crept in from one example supplier: currency and money format now follow the system region, the CSV and tax wording is neutral, and a plan for imperial units and profiles was added. A third workflow (6 agents rewriting, 1 re-rating) rewrote the plans for a broad international audience and re-rated their value. | `85c13f3` |
| 2026-09-29 | Three features built in parallel as a fourth workflow: one agent per feature in its own git worktree and branch, then an adversarial reviewer per branch who had to reproduce each defect, then a fix agent. The maintainer's session merged the branches, ran all test suites, and ran the new commands in the FreeCAD GUI. | |
| 2026-09-29 | Frame stiffness estimate (first stage): a 3D beam solver tested against closed forms, a model built from the profiles and joints, results as a range between loose and stiff joints, and a baseline to compare variants. The review found 7 issues; 6 were fixed. | `feature/frame-stiffness` |
| 2026-09-29 | Linear axis carriage: the clear run and stroke from the members that really block the carriage, and the belt length as metre ware in the cut list. The review found 4 issues; all were fixed. | `feature/linear-axis` |
| 2026-09-29 | Bracket placement: the user's own bracket part in the square corners of butt joints, as a link array, with calibration from two contact faces and a Hardware block in the cut list. The review found 6 issues; 5 were fixed (the sixth was these documentation rows). | `feature/brackets` |
| 2026-09-30 | Fix for a tie in choosing the through profile in frames turned 45°, which fell back to creation order (a variant of the pinwheel bug). Found by the bracket reviewer, written in a separate Claude Code session started from that suggestion, then checked (including that its tests fail without the fix) and merged by the maintainer's session. | `b5075a1` |
| 2026-09-30 | Stable piece marks (kept while a piece is unchanged, retired when it goes, marks for sheets, labels in the 3D view, a Renumber command), the rest of the panel fit check (cut tolerance, a cold check that the sheet stays in its slots, screw-hole play for sheets on the face) and panel fabrication (holes on the slot centre lines, rounded corners, sketch cutouts, DXF and SVG export, hole counts in the cut list). Written in one session without sub-agents, to save tokens; tested with new pytest and FreeCAD scripts and a GUI check. | `main` |

## Who did what

**The AI model:**
- wrote all the code, the tests, the README and this file;
- drew the icons, most of them with a script from the actual section geometry;
- chose the default profile dimensions.

**The human:**
- decided what to build and in what order;
- supplied reference material, such as datasheet images of angled profiles from a supplier;
- tested the workbench in FreeCAD and reported problems, such as butt joints on a square frame coming
  out uneven;
- decided when to commit and publish.

## What this means for you

- **Profile dimensions are approximate.** The model chose them from general knowledge of the common
  slot systems, not from vendor drawings, and they have not been checked against a datasheet. The
  weight classes follow generic rules. Check critical dimensions against your supplier's drawing
  before ordering; every dimension can be overridden per profile.
- **Mass and cost figures are estimates**, based on the simplified sections and the prices you enter.
- **Testing:** the model checked its work with automated tests (a pure-Python catalog and stock
  suite, and a FreeCAD suite covering geometry, joints, panels, pricing and document reload) and
  scripted GUI runs. The human tested it interactively. The code has not had an independent,
  line-by-line human review.

When you contribute, please say in your pull request whether you used AI tools, so this record stays
accurate.
