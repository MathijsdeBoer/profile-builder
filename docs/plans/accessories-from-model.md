# Accessories from the model: end caps, slot covers, panel seals and tagged STEP parts

| | |
|---|---|
| Status | Planned |
| Category | Manufacturing & ordering |
| Effort | M (first estimate M) |
| Value | medium |
| Proposed from | industrial, competitors |

## Problem

Small purchases add up and are routinely forgotten or guessed, which leads to a second order and a second delivery charge:
- end caps on exposed ends;
- slot cover strip for open slots (hygiene, dust, looks);
- seal or retaining strip for thin panels in wider slots (3 mm acrylic in a 6 mm slot rattles);
- clamps or screws every few hundred mm on on-face panels.
Imported STEP hinges, brackets and feet don't appear in the cut list or the cost at all.

## Proposal

An Accessories block in the report, computed from the model:
- End caps: one per exposed end (free ends, and flush run-through ends at corners, found with ends_of/through_member), by product.
- Slot cover: metres per slot system. For each profile that is the open faces times the slots per face (Columns/Rows cells) times the visible length (Length minus the zones covered by butting members, from JointStartOffset/JointEndOffset and support()), minus the slots in-slot panels occupy (_face_towards/_check_slot).
- Panel seal: metres per slot width, from the perimeter of in-slot panels where the slot opening minus the sheet thickness exceeds a set gap.
- On-face panel fasteners: perimeter divided by a pitch.
- Tagged parts: any App::Link or imported Part::Feature with a ProfileBuilderItem string property (set by a 'Tag as hardware' command), or placed in a 'Hardware' group, counted and priced per piece.
A per-profile CoverSlots setting (Auto / None / All) handles exceptions, and an allowance percentage covers waste. Prices live in a per-piece / per-metre accessories table in the Pricing object, with keys such as 'Slot cover 8' or 'Panel seal 8 / 4 mm'. North American suppliers such as 80/20 sell strip per foot, so the table should use the same length unit as profile prices rather than one of its own. Optional thin coloured strip solids show the covers.

## What exists today

No accessory counting and no tagged-part counting exist. Useful existing pieces:
- free ends are profiles with StartJoint or EndJoint set to None;
- joints.through_member plus ExtendThrough identify flush, exposed through ends;
- JointStartOffset/JointEndOffset;
- panels._face_towards and _check_slot locate the slots that in-slot panels occupy.
It overlaps heavily with hardware-bom: both add a per-piece price table and a report block.

## Implementation approach

Effort M confirmed overall. End caps, panel seal and tagged parts are S each; the slot-cover length estimate is the M part.

Merge this with hardware-bom into one 'Hardware & accessories' report block and one HardwarePrices map (per piece or per metre), so there are not two price tables.

Implementation, a read-only accessories.py:
- end_caps(doc): free ends plus through-member ends where ExtendThrough is on, grouped by product_key. A Vertical-rule cube gives 8 caps, on the post ends.
- panel_seal(doc): the perimeter of each in-slot panel where SlotOpening - Thickness > SealGap, grouped per slot width and thickness.
- tagged(doc): objects with a 'ProfileBuilderItem' string property, or inside a 'Hardware' group, counting ElementCount for App::Link arrays.
- A 'Tag as hardware' command adds that property to the selected objects. Profile Builder objects never link to them, so they stay out of the recompute graph. Vendors publish STEP files for most hardware, so the new angle is to count and price those imported parts rather than model them.
- Slot cover per profile: open faces x slots per face (Columns or Rows) x Length, minus the butting-member widths at joints on that face, minus in-slot panel edges.
  - The butting face is found with _face_towards(through_frame, -away).
  - A new CoverSlots enumeration (Auto / None / All) is added via add_properties.
- An 'AccessoryAllowance' percentage goes in pricing FIELDS.
- freecad_smoke: the cube has 8 end caps; the in-slot panel test frame gives the expected seal length.

## Blockers and caveats

- Slot-cover metres are an ordering estimate: nuts, doors and face-to-face double profiles are not detected without a proximity check between members.
- Tagging modifies the user's imported objects, so it must only happen through an explicit command.

## Risks

- It's an ordering estimate, not an exact count: slots later taken by T-nuts, brackets or doors aren't known, and T-junctions are approximate.
- A slot face pressed flat against another profile (double profiles) isn't really open, so that needs a proximity check between members.
- Reading tagged objects must stay read-only, with no links from Profile Builder objects into them, so they don't join the recompute graph.

## Prior art

item Engineeringtool adds caps to profile ends automatically. Vendors such as item, Bosch Rexroth, Misumi and 80/20 sell cover strips and seals by length. FrameForge's BOM counts App::Link parts and bodies with a Price property (create_bom.py traverse_assembly).

## Modules

- `cutlist.py`
- `pricing.py`
- `pricing_ui.py`
- `panels.py (per-edge perimeter)`
- `joints.py (exposed-end helper)`
- `feature.py (CoverSlots)`
- `commands.py`
- `tests/freecad_smoke.py`
