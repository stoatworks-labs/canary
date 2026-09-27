#!/usr/bin/env python3
"""Build the CANary 3D-printable four-part enclosure and export STEP/STL.

A lozenge: a superelliptical cross-section extruded between two flat end faces,
split on the horizontal centreline. Four parts:

    shell_bottom   floor + lower half of both flanks, the PCB channel, the
                   heat-set insert posts, and the lip that captures the ends
    shell_top      top + upper half of both flanks, the UI apertures, the bolt
                   counterbores, and the matching lip
    end_front      3 x etherCON NE8FBH
    end_rear       USB-C service port, stepped in to meet the receptacle
    led_insert     translucent tile + four light pillars for the LED window (PLA)
    switch_cover   push-on cap over the two service pinholes and the SW201 slot (PLA)

The lid carries the Stoatworks Labs mark and name and "CANary", the front plate CAN 1 /
CAN 2 / ETH under its connectors, the rear plate USB -- all engraved, from lettering/.

Cross-section is a SUPERELLIPSE (|x/a|^4 + |z/b|^4 = 1), not a true ellipse.
A true ellipse fails here: the three etherCON front plates are 25.6 mm tall and
span 81 mm across, so the section has to contain the point (40.5, 22.9) as well
as (56, 0). An ellipse through both needs a 70 mm internal height -- twice what
is otherwise required -- because it throws away all four corners. n = 4 keeps
the same soft profile with 40 mm.

Everything is derived from the placed board. Key facts, all read from
`hardware/canary.kicad_pcb` and `hardware/lib/ne8fbh.pdf`:

  * board is 100 x 81 mm and has NO mounting holes, so it is edge-captured in a
    channel rather than bolted to bosses
  * the three etherCONs exit one LONG edge and USB-C the opposite LONG edge, so
    the extrusion axis runs across the board's 81 mm dimension, not its 100
  * the etherCON cluster centre sits 6 mm left of the board centre, so the board
    is mounted off-centre in the case to put the cluster on the case centreline
  * the ESP32-S3-WROOM-1 (U301) hangs 5.25 mm past the board's REAR edge, antenna
    first, so the board is also mounted forward of centre and the case is deeper
    behind it than in front -- and the USB-C on that same edge is reached through
    an overmould-sized aperture rather than sitting flush in the end piece

Run:  <venv>/bin/python hardware/enclosure/gen_case_3dp.py [outdir]
      <venv>/bin/python hardware/enclosure/gen_case_3dp.py --flat [outdir]

`--flat` builds the same case on a FLAT-TOPPED section instead of the superellipse, so
that both shells print with their outer face on the plate and need no support at all.
Same envelope, same board channel position, same posts, apertures and end pieces; what
changes is the section, the board hold-down (ledges below, rails from the lid above,
because a floor-down bottom shell cannot print the closed groove's lip) and the guide
tubes, which get their 2.4 mm back. Default output dir hardware/enclosure/3dp-flat.

`--tube` builds the body as ONE piece -- top, bottom and both flanks -- that prints
standing on its rear end face, where every layer is the same 2.5 mm ring and nothing on
the shell overhangs in either section. Three parts: the tube and two flush end plates
screwed to it (8 x M3 into heat-set inserts in two full-length bosses and the channel
rails). The board slides in from the front. The guide tubes, the one feature that would
hang in the air standing up, get a 45-degree teardrop section and a fin down to the
wall, so the tube needs no support at all. Output dir hardware/enclosure/3dp-tube
(or 3dp-flat-tube with --flat).
"""
import json
import math
import pathlib
import sys

import cadquery as cq

_FLAGS = {a for a in sys.argv[1:] if a.startswith("--")}
_ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
SECTION = "flat" if "--flat" in _FLAGS else "lozenge"
TUBE = "--tube" in _FLAGS
# KiCad's board frame is LEFT-handed: X to the right, Y DOWN the screen, and the component
# side toward the viewer. Everything below is worked in that frame, with case Y running
# toward the etherCON edge and Z toward the component side -- which, read as a right-handed
# CAD frame, is the MIRROR IMAGE of the physical board. The first three articles were
# exported that way: with the board in its channel, etherCONs forward and components up,
# the USB-C was on the opposite side to its aperture. So every part is mirrored about the
# YZ plane on export, and only then. --as-kicad writes the unmirrored solids, for comparing
# against the earlier prints. Confirmed 2026-09-21: the mirrored front plate fits a unit.
MIRROR = "--as-kicad" not in _FLAGS
OUT = pathlib.Path(_ARGS[0] if _ARGS else
                   "hardware/enclosure/3dp" + ("-flat" if SECTION == "flat" else "")
                   + ("-tube" if TUBE else ""))

# ===========================================================================
# Parameters
# ===========================================================================

# ---- the board -----------------------------------------------------------
# Edge.Cuts X 20..120, Y 19..100.  Board-relative = absolute - (20, 19).
PCB_W, PCB_L, PCB_T = 100.0, 81.0, 1.6      # W across the case, L along its axis
PCB_UNDER = 8.0                              # clear space beneath the board

# Placed footprints, in board-relative coordinates
ETHERCON_X = (16.0, 44.0, 72.0)              # J201, J202, J401 -- exit y = 81
ETHERCON_Y = 73.0                            # their footprint origin (= the latch-
                                             # post midpoint), 8 mm back from the edge
USBC_X = 86.0                                # J102 -- exits y = 0
LED_X, LED_Y = 3.5, (7.0, 11.0, 15.0, 19.0)  # D301..D304, 0603, emit +Z
BTN_X, BTN_Y = 8.0, (29.0, 39.0)             # SW301, SW302 PTS645, actuate +Z
DIP_X, DIP_Y = 10.0, 57.5                    # SW201 CAN terminator, must stay
                                             # field-reachable (LAYOUT.md rule 6)

# ---- Neutrik NE8FBH, from hardware/lib/ne8fbh.pdf (drawing 20003890) ------
BORE_D = 22.4               # >= 22.00 spec; +0.4 for FDM hole shrink
SCREW_D = 3.4               # >= 3.20 spec; +0.2 for FDM hole shrink
SCREW_OFF = 19.8 / 2.0      # each screw at (+/-9.90, +/-9.90), DIAGONALLY opposed
# Which diagonal, in the board frame ("nesw" = (+x,-z) and (-x,+z)). All three connectors
# are placed identically (rot 180) so all three share it. Derived from the drawing's front
# view and CONFIRMED on 2026-09-21: the mirrored-export front plate went onto a unit's three
# connectors with all six panel screws, the right way round.
ETHERCON_DIAG = "nesw"
NE8FBH_AXIS = 12.5          # connector axis above the PCB top surface
NE8FBH_PLATE_W = 25.0
NE8FBH_PLATE_H = 25.6
# The plate is NOT centred on the axis. Drawing 20003890 dimensions 12,5 from the
# plate's BOTTOM edge up to the axis, inside an overall 25,6 -- so the plate runs
# 12.5 below the axis and 13.1 above it. Checking it as +/- 25.6/2 understates the
# top corner by 0.3 mm, which is the corner the superellipse has to contain.
NE8FBH_PLATE_BELOW = NE8FBH_AXIS
NE8FBH_PLATE_ABOVE = NE8FBH_PLATE_H - NE8FBH_AXIS
# Same drawing, PCB-layout view: 3,81 from the panel's rear face down to the first
# latch post, and 8,89 between the two latch posts. The footprint's origin is their
# midpoint (see hardware/lib/canary.pretty/Neutrik_etherCON_NE8FBH.kicad_mod), so
# the panel the connector bolts to sits this far in FRONT of the footprint origin.
NE8FBH_PANEL_FROM_ORIGIN = 3.81 + 8.89 / 2.0            # = 8.255
# 3,45 in the front view runs from the plate's bottom edge down to the pin tips.
# Taking the plate bottom as resting on the PCB top surface -- which is also what
# makes NE8FBH_AXIS a height above that surface -- the pins hang this far below the
# board. MEASURE ME: the drawing does not state the plate-bottom standoff directly,
# and it is the same assumption NE8FBH_AXIS rests on.
NE8FBH_PIN_BELOW_PCB = 3.45 - PCB_T                     # = 1.85
# The drawing does not dimension the protrusion in FRONT of the mounting plate.
# Its B-series sibling NC5FBV (drawing ST-NC5FBV) dimensions 3.5 mm, and both take
# the identical panel cutout, so 3.5 mm is the working figure and END_T must stay
# under it. CONFIRM against a real NE8FBH before a batch -- docs/ENCLOSURE.md open
# item 5 already asks for exactly this check.
B_SERIES_PANEL_MAX = 3.5

# ---- shell ---------------------------------------------------------------
WALL = 2.5
SE_N = 4.0                  # superellipse exponent
INNER_A = 66.0              # inner semi-width  -> 132 mm internal
INNER_B = 20.0              # inner semi-height ->  40 mm internal

# ---- the flat section (--flat) --------------------------------------------
# The superellipse cannot be printed outer-face-down: only the outermost 3.4 mm of each
# flank is steeper than 45 deg, so a 34 mm band of the visible skin per side would sit on
# support at 2..30 deg from horizontal. Flat top and bottom faces fix that, and the four
# long edges get a fillet whose lower 45 deg is replaced by a 45 deg chamfer tangent to
# it. A plain fillet starts horizontal at the plate: at R10 its second layer would hang
# 1.7 mm past its first. The chamfer takes over exactly where the arc drops below 45 deg,
# so from the plate up nothing overhangs more than the layer height. The chamfer leg that
# is tangent to a radius r at 45 deg is r * (2 - sqrt 2).
BOX_R = 10.0                # fillet radius on the four long OUTER edges


def box_r(a):
    """Fillet radius of a flat-section profile offset from the OUTER one to semi-width a.

    Offsetting a fillet-plus-tangent-chamfer profile inward by t leaves an arc of r - t
    about the same centre and a parallel chamfer that is still tangent to it, so every
    offset section (inner, rebate, tongue, end piece) is the same construction with a
    smaller radius and the wall stays a uniform WALL everywhere.
    """
    return max(BOX_R - (OUTER_A - a), 0.3)


def box_ch(r):
    return r * (2.0 - math.sqrt(2.0))

# Board sits off-centre so the etherCON cluster lands on the case centreline.
# GAP_L - GAP_R must equal 2 * (PCB_W/2 - ETHERCON_X[1]) = 12 mm.
GAP_L = 22.0                # clear strip left of the board -- the legend area
GAP_R = 10.0                # clear strip right of the board

# ---- the ESP32 module, which does not fit on the board -------------------
# U301 is an ESP32-S3-WROOM-1 at board-relative (34.0, 7.5), unrotated. The module's
# 25.5 mm body is centred on that origin with the PCB antenna at its -Y end, so it
# hangs 5.25 mm PAST the board's rear edge -- deliberately, an antenna wants to
# overhang -- and that is the same edge the USB-C exits. Nothing in this file knew
# about it, so the case gave the antenna 0.5 mm and fouled it on assembly.
ESP32_X, ESP32_Y = 34.0, 7.5
ESP32_BODY_W, ESP32_BODY_L = 18.0, 25.5
ESP32_OVERHANG = ESP32_BODY_L / 2.0 - ESP32_Y           # = 5.25
ANTENNA_CLEAR = 1.75        # air between the antenna tip and the rear end piece

# FRONT_CLEAR cannot grow: the three etherCONs bolt to the front end piece, so the
# board's front edge has to stay where it is. ALL the extra depth goes behind it.
FRONT_CLEAR = 0.5
REAR_CLEAR = ESP32_OVERHANG + ANTENNA_CLEAR             # = 7.0
INNER_L = PCB_L + FRONT_CLEAR + REAR_CLEAR              # = 88.5

# ---- four-part joinery ---------------------------------------------------
END_T = 2.5                 # end piece thickness -- must be < B_SERIES_PANEL_MAX
SKIN = 1.0                  # outer skin left in front of an end piece = the lip
FIT = 0.25                  # per-side clearance on captured parts
TONGUE_W = 1.2              # parting-line tongue (bottom) / groove (top)
TONGUE_H = 1.5
TONGUE_INSET = 0.6

# ---- fasteners -----------------------------------------------------------
INSERT_PILOT_D = 3.7        # M3 x 5.7 heat-set, per docs/ENCLOSURE.md
INSERT_DEPTH = 10.5         # deep enough that BOTH M3 x 20 and M3 x 25 clear the bottom
BOSS_D_L, BOSS_D_R = 9.0, 7.0   # right-hand strip is only 10 mm wide
SCREW_CLEAR_D = 3.4
SCREW_HEAD_D = 6.2
# The counterbore floor is an ABSOLUTE height, not a depth below the top face. The shell is
# a superellipse, so the outer skin over the right-hand posts sits 2.4 mm lower than over
# the left ones; cutting a fixed depth below the top face missed the right posts entirely
# and left those two screws bearing on skin sloping ~24 deg. One height for all four gives
# every screw a flat, square seat and makes ONE screw length fit the whole case.
Z_SEAT = 15.5

# The two shells each carried a post ending at EXACTLY z = 0, so the halves met post-to-post
# with no clearance at all and the posts, not the parting faces, decided whether the case
# closed. Measured off the shipped meshes: bottom post 0.000, top post 0.000.
#
# Two independent things can hold that open, so both are relieved:
#   * POST_GAP lifts the top shell's post clear, making the parting faces and the tongue
#     the closing feature -- which is what locates the halves anyway.
#   * INSERT_RELIEF clears a heat-set insert that has not gone fully home. An M3 insert
#     standing 0.5 mm proud of a post face is invisible and will hold the case open on its
#     own, and no gap at the parting line fixes that.
POST_GAP = 0.3
INSERT_RELIEF_D = 5.5
INSERT_RELIEF_H = 0.8

# ---- board channel -------------------------------------------------------
CH_SLOT_H = PCB_T + 0.6
CH_ENGAGE_L = 3.5           # left edge engagement -- the deep side
CH_ENGAGE_R = 2.5           # right edge engagement
CH_INSERT_SLACK = 0.5       # extra left-groove depth so the board can go in
CH_ABOVE = 2.0

# ---- apertures -----------------------------------------------------------
LED_WIN = (10.0, 22.0)      # window over the LED column; takes a smoked insert
LED_WIN_REBATE = 1.2        # rebate depth for that insert
# The insert is now a PRINTED part, not acrylic: a tile that drops into the rebate, in a
# translucent filament (natural or white PLA), carrying four light pillars that reach down
# through the window to just above each 0603 so the four indicators stay four, not one
# 30 mm-away blur. Printed tile-down; sized to the rebate less a slip clearance.
LED_INSERT_CLEAR = 0.15     # per side, insert vs rebate
LED_PILLAR = (4.0, 3.0)     # pillar section: across the window (x) by along it (y)
LED_PILLAR_GAP = 1.0        # pillar bottom above the LED top (0603 body 0.55 mm)
LED_0603_H = 0.55
# SW301 is EN/reset and SW302 is the BOOT strap (mcu.kicad_sch pin-map note) --
# both are service controls, so they get guided tool pinholes rather than the
# ~26 mm plungers a finger-operated button would have needed at this depth.
BTN_D = 4.0
BTN_GUIDE_OD = 8.5          # internal guide tube, so a wire finds the switch
# The tubes used to run down to Z_PCB_TOP + 8.0 = -2.4, i.e. 2.4 mm BELOW the parting
# plane -- which made them the lowest point of the top shell. orient_for_print drops each
# part onto z = 0, so the shell printed balanced on two 8.5 mm tubes with its entire
# 137 x 93 mm rim 2.4 mm in the air: 8 x 18 mm of bed contact on a part that should have
# had the whole rim down. That is a warp waiting to happen, and it warped.
#
# Nothing may cross the parting plane. The cost is 2.4 mm less guidance -- the bore now
# ends 10.4 mm above the board rather than 8.0 -- which a stiff wire down a 4 mm hole
# still finds, these being service controls poked twice a year.
#
# The flat section prints the top shell top-face-DOWN, so its parting plane is the top of
# the print and nothing about it is load-bearing; the tubes get their 8.0 mm back there.
BTN_GUIDE_Z0 = 0.0          # lozenge; the flat value is derived below (Z_PCB_TOP + 8)
BTN_GUIDE_ABOVE_PCB = 8.0
DIP_SLOT = (13.0, 5.5)      # screwdriver access to SW201
# The switch cover: one cap over all three service apertures -- the two pinholes and the
# SW201 slot -- printed in the LED insert's PLA. It needs no change to the case: two pegs
# push into the pinholes and a key drops into the slot, and it pulls off by hand when the
# switches are wanted. Its underside is the lid's own surface, its top is flat, so it
# prints top-face down and sits on the curve without rocking.
SW_COVER_T = 1.2            # over the highest point of the lid under it
SW_COVER_MARGIN = 2.0       # past the pinholes' and the slot's edges
SW_COVER_LED_GAP = 0.5      # short of the LED rebate, which the first pinhole nearly meets
SW_COVER_R = 2.0            # plan-view corner radius
SW_COVER_PEG_D = 3.9        # into the 4.0 pinholes: the push fit that holds it on
SW_COVER_PEG_L = 4.0        # below the lid surface; the bores run 20 mm deeper
SW_COVER_KEY_CLEAR = 0.15   # per side, key vs slot -- it locates, the pegs hold
SW_COVER_KEY_L = 2.0        # into the 2.5 mm wall; stops short of the cavity
# The tube's cover sits FLUSH, in a pocket in the lid, instead of on top of it. The lid
# falls 0.7 mm across the cover's 17 mm, but it is within 0.13 mm of its own chord there,
# so the cover is a flat slab on a plane tilted to that chord: its top is flush to under
# half a layer, and it still prints on a flat face. The pocket floor is the same plane,
# SW_POCKET_T lower. A notch past the pocket's front end, with a bevel under the cover's
# edge above it, takes a small screwdriver to lever the cover out.
SW_POCKET_T = 1.2           # cover thickness = pocket depth (6 layers at 0.2)
SW_POCKET_CLEAR = 0.15      # per side, cover vs pocket
SW_POCKET_FLOOR_MIN = 1.0   # validate(): wall left under the pocket, at its thinnest
SW_NOTCH_W = 6.0            # lever notch, across the case
SW_NOTCH_L = 2.5            # ...and out past the pocket's front end
SW_NOTCH_BEVEL = 0.6        # 45-deg bevel under the cover's front edge, for the blade
SW_COVER_KEY_FLUSH_L = 1.0  # the key only locates; the pocket floor is ~1.2 mm thick
USBC_W, USBC_H = 9.7, 3.8
# The receptacle mouth is flush with the board's rear edge, and the rear end piece sits
# REAR_CLEAR (7 mm) behind that edge so the ESP32 antenna has room. A plug cannot reach
# across that: its shell is only ~6.5 mm long, so a plain aperture in the plate left the
# port usable by slim cables only, and then only just. The plate therefore carries a STEP:
# a rectangular well that projects inward from the plate's inner face to USBC_WELL_GAP
# short of the board edge, with the plug aperture in its floor. The plug's overmould enters
# the well and either passes the floor aperture (a spec-sized moulding, 12.35 x 6.5 max)
# and seats fully, or stops on the floor USBC_WELL_WALL + USBC_WELL_GAP from the mouth --
# the same loss as any 2 mm panel. The rest of the plate stays where it was, so the
# antenna keeps its clearance and the shell still encloses the whole board.
USBC_PLUG_W, USBC_PLUG_H = 14.0, 9.0      # floor aperture: spec overmould + FDM shrink
USBC_WELL_W, USBC_WELL_H = 17.5, 12.5     # well cavity: room for a chunky moulding
USBC_WELL_WALL = 1.6                      # well wall and floor thickness (4 x 0.42 lines)
USBC_WELL_GAP = 0.8                       # well floor (inner face) short of the board edge
USBC_WELL_CHAMFER = 1.0                   # 45-deg lead-in at the plate's outer face

# ---- lettering -----------------------------------------------------------
# Engraved, never embossed: nothing may stand proud of a face that prints on the plate
# (the rear plate and the flat shells print outer face DOWN), and a recess needs no
# clearance from anything it passes. Everything is laid out on a PAGE -- u to the reader's
# right, v up, as the face is read from outside -- in the PHYSICAL frame, then mirrored into
# the board frame this file works in, so the export's own mirror turns it back the right
# way round. The font is Montserrat, the brand face, cut to static weights (lettering/,
# OFL); the mark is the website's brand master traced to polygons by lettering/trace_mark.py.
LETTER_DIR = pathlib.Path(__file__).resolve().parent / "lettering"
FONT_BOLD = LETTER_DIR / "Montserrat-Bold.ttf"
FONT_XBOLD = LETTER_DIR / "Montserrat-ExtraBold.ttf"
MARK_FILE = LETTER_DIR / "stoatworks-mark.geojson"
CAP_EM = 0.70               # Montserrat cap height per em (measured: 'H' at 10 = 7.00)
LETTER_DEPTH = 0.6          # 3 layers at 0.2, and leaves >= 1.7 mm of a 2.3-2.5 mm plate
PORT_CAP = 5.0              # CAN 1 / CAN 2 / ETH / USB
PORT_LABELS = ("CAN 1", "CAN 2", "ETH")     # J201, J202, J401 -- ETHERCON_X order
# Under each etherCON: its flange stops 12.5 below the axis (z -10.4) and its lower screw
# hole at z -9.5, so the label sits in the clear band beneath, centred at this height.
PORT_LABEL_Z = -15.5
USB_LABEL = "USB"
USB_LABEL_GAP = 2.5         # label's baseline above the lead-in chamfer's top edge
# The lid: mark, a two-line STOATWORKS / LABS wordmark as on the website's lockup, and the
# product name, stacked and centred in the clear part of the top face -- right of the LED
# window, pinholes and SW201 slot (board frame), and read with the etherCONs toward you.
MARK_W = 44.0               # mark width; at this size the stoat's outline is ~0.7 mm
WORD_CAP = 4.5
WORD_LEAD = 2.5             # between STOATWORKS and LABS
NAME = "CANary"
NAME_CAP = 7.0
LID_GAPS = (4.0, 6.0)       # mark -> wordmark, wordmark -> name
LID_CLEAR = 3.0             # nearest approach to a top-face opening
LID_RIGHT = 45.0            # board-frame x where the lid's curve has fallen ~1 mm

# ===========================================================================
# Derived
# ===========================================================================
# Posts are clipped to a section HALF A WALL outside the cavity, not to the cavity
# itself. Clipping them exactly to the inner surface makes the post's top face coincident
# with the shell's own spline, and OCC handles that union badly: it silently dropped the
# post at (-52.5, +35.25) on one run and produced 458 non-manifold edges there on the
# next. Burying the top of each post inside the wall gives the union real overlap instead
# of a tangency. The result is the same shape -- that material is already shell.
POST_CLIP = (INNER_A + WALL / 2.0, INNER_B + WALL / 2.0)

OUTER_A = INNER_A + WALL
OUTER_B = INNER_B + WALL
OUTER_L = INNER_L + 2 * WALL

# Case X origin is the etherCON cluster centre.
X_PCB_L = -(ETHERCON_X[1])              # board's left edge,  = -44
X_PCB_R = PCB_W - ETHERCON_X[1]         # board's right edge, = +56
Y_IN_F = INNER_L / 2.0                  # internal front face (etherCONs)
Y_IN_R = -INNER_L / 2.0                 # internal rear face (USB-C + antenna)

# The board is no longer centred in the case. It sits forward by half the difference
# between the two end clearances, which keeps FRONT_CLEAR at the etherCON end and puts
# the whole of REAR_CLEAR behind the board for the antenna.
Y_BOARD_OFF = (REAR_CLEAR - FRONT_CLEAR) / 2.0          # = 3.25

Z_BOT_IN = -INNER_B
Z_TOP_IN = INNER_B
Z_PCB_BOT = Z_BOT_IN + PCB_UNDER
Z_PCB_TOP = Z_PCB_BOT + PCB_T
Z_AXIS = Z_PCB_TOP + NE8FBH_AXIS        # etherCON axis
# The plug aperture is centred on the receptacle shell -- 8.94 x 3.26 mm for the HRO
# TYPE-C-31-M-12, sitting on the board's top surface -- not on an inflated stand-in.
USBC_ZC = Z_PCB_TOP + 3.26 / 2.0        # = -8.77
USBC_WELL_DEPTH = REAR_CLEAR - USBC_WELL_GAP    # well projection past the plate's inner face

RAIL_L_FACE = X_PCB_L + CH_ENGAGE_L
RAIL_R_FACE = X_PCB_R - CH_ENGAGE_R
# The left groove must be deep enough to swallow the board far enough for its
# right edge to clear the right rail's lip on the way in, and then let it slide
# back until BOTH edges are engaged.
SLOT_L_ROOT = X_PCB_L - CH_ENGAGE_R - CH_INSERT_SLACK
SLOT_R_ROOT = X_PCB_R + 0.5

if SECTION == "flat":
    BTN_GUIDE_Z0 = Z_PCB_TOP + BTN_GUIDE_ABOVE_PCB      # = -2.4, the original intent

# ---- board hold-down, flat section only -----------------------------------
# Floor-down, the bottom shell cannot print the closed groove: its lip is a 1.4 mm
# ceiling cantilevered 6.5 mm over the slot, with nothing under it but air. So the
# groove becomes an open LEDGE the board rests on, with a locating riser outboard of
# each board edge, and the hold-down moves to the top shell: thin rails that come down
# from the lid onto the board's edge strips, which the flipped top shell prints as plain
# vertical walls. Insertion changes with it -- the board drops straight in.
#
# Where a rail may run is set by what the board carries within 3 mm of each long edge.
# Courtyards, board-relative, from hardware/canary.kicad_pcb:
#   left   D301..D304 from x 2.78 (y 5.5..20.6, under the LED window)
#          SW301/SW302 from x 2.96 (y 25.6..42.5)
#   right  F101 to x 97.22 (y 9.7..14.4), C109 to 99.0 (y 16.5..17.6),
#          L102 to 97.62 (y 24.8..29.3)
# The rail sits LEDGE_CLEAR inboard of the nominal edge so that it is still over the
# board when the board is hard against the far riser, and the board's own courtyard
# clearance has to absorb rail width plus twice that slack.
LEDGE_CLEAR = 0.5           # riser face outboard of the board edge, each side
HOLD_W = 1.26               # 3 x 0.42 mm lines
HOLD_GAP = 0.4              # rail tip above the board's top surface (board is +/-0.16)
EDGE_KEEPOUT_L = 2.78       # nearest courtyard to the left edge, board-relative x
EDGE_KEEPOUT_R = 100.0 - 97.22   # ...and to the right edge, as a distance
HOLD_RAILS = {              # board-relative y spans each rail covers
    "left": ((24.5, PCB_L),),               # starts past the LED window (y 2..24)
    "right": ((0.0, 15.0), (30.5, PCB_L)),  # skips C109 and L102
}
HOLD_X = {                  # case x of each rail's two faces
    "left": (X_PCB_L + LEDGE_CLEAR, X_PCB_L + LEDGE_CLEAR + HOLD_W),
    "right": (X_PCB_R - LEDGE_CLEAR - HOLD_W, X_PCB_R - LEDGE_CLEAR),
}
RISER_L_FACE = X_PCB_L - LEDGE_CLEAR
RISER_R_FACE = X_PCB_R + LEDGE_CLEAR

# ---- one-piece tube (--tube) ----------------------------------------------
# Standing on an end face, every layer of the body is the section's own ring, so the
# shell itself needs no support in either section. What changes:
#   * the board slides in along Y, so the left groove needs no insertion slack: both
#     grooves engage CH_ENGAGE_R and the board is located +/-0.5 mm between the roots.
#     That also lifts the left lip clear of D301..D304, whose 0603 bodies reach 0.35 mm
#     under the lozenge's 3.5 mm lip (LED_0603 at board x 3.15..3.95, lip face at 3.5).
#   * the end plates sit ON the ends, flush with the outside, and are screwed to the
#     tube: 8 x M3 into heat-set inserts in two full-length bosses under the top wall
#     (the old post positions) and in the channel rails. The rails grow taller so the
#     lower pilots have wall around them.
#   * the guide tubes are 22 mm horizontal cantilevers when the tube stands up. Each gets
#     a 45-degree teardrop section pointing at the plate and a thin fin under the apex
#     down to the wall, so no layer of them hangs in the air. The fin's root runs along
#     the top wall next to the LED window, so the window moves TUBE_LED_SHIFT left here.
TUBE_L = INNER_L                    # body length; end plates add END_T each side
TUBE_RAIL_TOP = Z_PCB_TOP + 5.0     # rail top, up from Z_PCB_TOP + CH_ABOVE
TUBE_SCREW_X_BL = -50.0             # lower pilots: in the rail blocks
TUBE_SCREW_X_BR = SLOT_R_ROOT + 1.0 + INSERT_PILOT_D / 2.0 + 1.0    # 1 mm past the groove
TUBE_FIN_T = 1.2                    # 3 x 0.42 mm lines
TUBE_FIN_BURY = 1.0                 # fin top inside the teardrop, so the union overlaps
TUBE_LED_SHIFT = -1.5               # LED window moved left, clear of the fin root
# Internal bracing (2026-09-27). The tube is one 2.5 mm ring 137 x 45 mm, and its long flat-
# ish top and bottom are what flex. Two kinds of stiffener, both clear of everything that
# has to pass through the tube or sit in it:
#   * HOOP BANDS round the inside of the section at three stations along the tube. Standing
#     on the rear end they are horizontal ledges, so each has a 45-degree underside: BAND_D
#     inward, BAND_W flat on top of that. A band stops short of the lid's opening strip (the
#     LED window, pinholes, SW201 slot and cover pocket, BAND_OPENING_CLEAR round them),
#     since a band across the window would shade the LEDs and one across the pinholes would
#     block the guide tubes' mouths.
#   * LONGITUDINAL RIBS the full length, two under the lid and two on the floor. Standing
#     up they are vertical walls: nothing to support.
# Clearances the checks hold them to: the board's swept path (it slides in from the front)
# with its pins below and components above, the etherCON plates' swept path at the front,
# the rear plate's USB-C well, and the end-face insert pilots.
BAND_D = 2.0                        # inward from the inner wall
BAND_W = 2.5                        # flat thickness along Y, above the 45-degree underside
BAND_Y_TOP = (-26.0, 2.0, 32.0)     # each band's top face (+Y, the upper face as printed)
BAND_OPENING_CLEAR = 2.0
RIB_H = 2.5                         # inward from the inner wall
RIB_T = 1.7                         # 4 x 0.42 mm lines
RIB_TOP_X = (0.0, 30.0)             # under the lid, clear of the opening strip (x < -21)
RIB_FLOOR_X = (-20.0, 15.0)         # on the floor, clear of the USB-C well (x 31.6..52.4)
if TUBE:
    RAIL_L_FACE = X_PCB_L + CH_ENGAGE_R
    SLOT_L_ROOT = X_PCB_L - 0.5
    BTN_GUIDE_Z0 = Z_PCB_TOP + BTN_GUIDE_ABOVE_PCB

POST_X_L = X_PCB_L - 4.0 - BOSS_D_L / 2.0   # clear of the LED window rebate
POST_X_R = X_PCB_R + 1.0 + BOSS_D_R / 2.0
POST_Y = INNER_L / 2.0 - END_T - max(BOSS_D_L, BOSS_D_R) / 2.0 - 2.0
POSTS = [(POST_X_L, +POST_Y, BOSS_D_L), (POST_X_L, -POST_Y, BOSS_D_L),
         (POST_X_R, +POST_Y, BOSS_D_R), (POST_X_R, -POST_Y, BOSS_D_R)]

# Screw travel, measured from the seat rather than from the top face. REACH is how far the
# screw goes before it meets the insert; anything beyond that is engagement, capped by the
# insert's own 5 mm length, and it must not reach the bottom of the pocket.
INSERT_LEN = 5.0            # M3 x 5 x 4.0 heat-set (OD 4.0 suits the 3.7 pilot)
SCREW_REACH = Z_SEAT
SCREW_MIN = SCREW_REACH + 4.0                    # >= 1.3 x D engaged
SCREW_MAX = SCREW_REACH + INSERT_DEPTH - 1.0     # stop short of the pocket floor


def bx(x):
    """board-relative X -> case X"""
    return x - ETHERCON_X[1]


def by(y):
    """board-relative Y -> case Y"""
    return y - PCB_L / 2.0 + Y_BOARD_OFF


# ===========================================================================
# Primitives
# ===========================================================================
def se_points(a, b, steps=64):
    pts = []
    for i in range(steps):
        th = 2.0 * math.pi * i / steps
        c, s = math.cos(th), math.sin(th)
        x = a * math.copysign(abs(c) ** (2.0 / SE_N), c)
        z = b * math.copysign(abs(s) ** (2.0 / SE_N), s)
        pts.append((x, z))
    return pts


def se_prism(a, b, length, y=0.0):
    """Superelliptical cross-section in XZ, extruded along Y, centred on y.

    A periodic SPLINE, not a polyline. Faceting the section into 180 straight
    segments gave a valid solid but a 180-strip "curve": every boolean carried
    it, and the STEP export was all planar faces (assembly 5.6 MB, top shell
    2.2 MB). Through a spline those become 3.4 MB and 1.6 MB, and the surface
    is actually curved.

    The spline bulges very slightly outside the true superellipse between
    control points -- about 0.15 mm per side at 64 points, an order below FDM
    shrink. Interference between parts is checked against the built solids, not
    the nominal profile, so this is accounted for rather than assumed away.
    """
    return (cq.Workplane("XZ")
            .spline(se_points(a, b), periodic=True)
            .close()
            .extrude(length / 2.0, both=True)
            .translate((0, y, 0)))


def box_prism(a, b, length, y=0.0):
    """Flat-section profile in XZ, extruded along Y, centred on y.

    A 2a x 2b rectangle whose four corners are a fillet of box_r(a) with its lower 45 deg
    replaced by the tangent chamfer (see BOX_R). Lines and arcs, not a spline: every face
    is planar or cylindrical, which the booleans downstream like far better than the
    lozenge's spline surface.
    """
    r = box_r(a)
    c = box_ch(r)
    k = math.sqrt(0.5)
    cx, cz = a - r, b - r                       # fillet centre, first quadrant
    m22 = (r * math.cos(math.radians(22.5)), r * math.sin(math.radians(22.5)))
    w = cq.Workplane("XZ").moveTo(-(a - c), b).lineTo(a - c, b)
    # top-right: chamfer down to the 45 deg point, arc round to the flank
    w = w.lineTo(cx + r * k, cz + r * k)
    w = w.threePointArc((cx + m22[0], cz + m22[1]), (a, cz))
    w = w.lineTo(a, -cz)
    # bottom-right: arc from the flank to 45 deg, chamfer onto the floor
    w = w.threePointArc((cx + m22[0], -cz - m22[1]), (cx + r * k, -cz - r * k))
    w = w.lineTo(a - c, -b).lineTo(-(a - c), -b)
    # bottom-left
    w = w.lineTo(-(cx + r * k), -cz - r * k)
    w = w.threePointArc((-(cx + m22[0]), -cz - m22[1]), (-a, -cz))
    w = w.lineTo(-a, cz)
    # top-left
    w = w.threePointArc((-(cx + m22[0]), cz + m22[1]), (-(cx + r * k), cz + r * k))
    w = w.close()
    return w.extrude(length / 2.0, both=True).translate((0, y, 0))


def section_prism(a, b, length, y=0.0):
    """The case section at semi-axes (a, b) -- superellipse or flat, per SECTION."""
    if SECTION == "flat":
        return box_prism(a, b, length, y)
    return se_prism(a, b, length, y)


def inside(x, z, a, b):
    """Is (x, z) inside the section with semi-axes (a, b)?"""
    if SECTION != "flat":
        return (abs(x / a) ** SE_N + abs(z / b) ** SE_N) <= 1.0
    r = box_r(a)
    c = box_ch(r)
    ax, az = abs(x), abs(z)
    if ax > a or az > b:
        return False
    cx, cz = a - r, b - r
    if ax > cx and az > cz:
        # In the corner: above its diagonal the chamfer is the boundary, below it
        # the arc. They are tangent where the diagonal crosses them.
        if az - cz >= ax - cx:
            return ax + az <= a + b - c
        return math.hypot(ax - cx, az - cz) <= r
    return True


def skin_z(x, a=OUTER_A, b=OUTER_B):
    """Height of the section's surface above the parting line at this x (0 if outside)."""
    ax = abs(x)
    if SECTION != "flat":
        t = 1.0 - (ax / a) ** SE_N
        return b * (t ** (1.0 / SE_N)) if t > 0.0 else 0.0
    r = box_r(a)
    c = box_ch(r)
    if ax > a:
        return 0.0
    if ax <= a - c:
        return b
    if ax <= a - r + r * math.sqrt(0.5):
        return a + b - c - ax                       # on the chamfer
    return (b - r) + math.sqrt(max(r * r - (ax - (a - r)) ** 2, 0.0))   # on the arc


def teardrop_zcyl(d, z0, z1, x, y, point=-1):
    """A Z cylinder whose section is a circle with a 45-degree point in +/-Y.

    Printed with Y vertical (the tube standing on an end), a round boss lying on its
    side has a horizontal underside; the point makes every layer of it no more than one
    layer height wider than the one below. The point is r*sqrt(2) from the centre.
    """
    r = d / 2.0
    k = math.sqrt(0.5)
    s = 1.0 if point > 0 else -1.0
    w = (cq.Workplane("XY", origin=(0, 0, z0))
         .moveTo(x - r * k, y + s * r * k)
         .lineTo(x, y + s * r * math.sqrt(2.0))
         .lineTo(x + r * k, y + s * r * k)
         .threePointArc((x, y - s * r), (x - r * k, y + s * r * k))
         .close())
    return w.extrude(z1 - z0)


def fin_yz(x, t, y_top, z_free, z_wall):
    """A right-triangle fin in a YZ plane, t thick, centred on x.

    Its top edge (y_top) runs the length of a boss from z_free to z_wall; its underside
    drops away from the free end at 45 degrees and meets the wall (z_wall) y_top -
    (z_wall - z_free) lower. Printed with Y vertical it holds up the boss's lowest
    layers, and is itself never steeper than 45 degrees from the plate.
    """
    h = z_wall - z_free
    return (cq.Workplane("YZ", origin=(x - t / 2.0, 0, 0))
            .polyline([(y_top, z_free), (y_top, z_wall), (y_top - h, z_wall)])
            .close()
            .extrude(t))


def tube_bosses():
    """[(x, z, d)] of the two full-length bosses under the top wall (--tube)."""
    out = []
    for x, d in ((POST_X_L, BOSS_D_L), (POST_X_R, BOSS_D_R)):
        # buried 1 mm into the wall's inner surface, as the posts are half a wall
        out.append((x, skin_z(x, INNER_A, INNER_B) - d / 2.0 + 1.0, d))
    return out


def opening_strip():
    """(x0, x1, y0, y1) round every lid opening on the left, grown by BAND_OPENING_CLEAR."""
    ops = [o for o in lid_openings() if o[0] < 0.0]
    c = BAND_OPENING_CLEAR
    return (min(o[0] for o in ops) - c, max(o[1] for o in ops) + c,
            min(o[2] for o in ops) - c, max(o[3] for o in ops) + c)


def band_span(y_top):
    """(y of the underside's foot at the inner wall, y of the top face)."""
    return y_top - BAND_W - BAND_D, y_top


def tube_band(y_top):
    """One hoop band: flat BAND_W on top of a 45-degree underside BAND_D deep (--tube)."""
    y_lo, _ = band_span(y_top)
    a, b = INNER_A, INNER_B
    # Rooted half a wall into the shell, as the posts are: a real overlap, not a tangency.
    outer = se_prism(*POST_CLIP, BAND_W + BAND_D + 1.0, y=(y_lo - 1.0 + y_top) / 2.0)
    # The cutter: the full inner section below the band, a cone shrinking by BAND_D over
    # BAND_D of height (the underside), then the shrunk section up through the top.
    # The cone runs E past the inner surface, still at 45 degrees, so the underside meets
    # the wall at an angle inside the shell rather than edge-on at its surface (edge-on,
    # OCC's clean() refused the union).
    E = 0.3
    cone = (cq.Workplane("XZ", origin=(0, y_top - BAND_W, 0))
            .spline(se_points(a - BAND_D, b - BAND_D), periodic=True).close()
            .workplane(offset=BAND_D + E)
            .spline(se_points(a + E, b + E), periodic=True).close()
            .loft(ruled=True))
    cut = (cone.union(se_prism(a - BAND_D, b - BAND_D, BAND_W + 2.0,
                               y=y_top - BAND_W / 2.0 + 0.5))
           .union(se_prism(a + E, b + E, 2.0, y=y_lo - E - 0.95)))
    band = outer.cut(cut)
    # Stop short of the lid's opening strip, over the band's WHOLE span: a gap cut across
    # only part of it would leave a flat ledge hanging over air.
    x0, x1, y0, y1 = opening_strip()
    if y_lo < y1 and y_top > y0:
        band = band.cut(zbox(x1 - x0, BAND_W + BAND_D + 2.0, 5.0, OUTER_B + 5.0,
                             (x0 + x1) / 2.0, (y_lo + y_top) / 2.0))
    return band


def tube_ribs():
    """The four full-length longitudinal ribs, two under the lid and two on the floor."""
    L = TUBE_L
    clip = section_prism(*POST_CLIP, L + 10.0)
    out = None
    for x, up in [(x, True) for x in RIB_TOP_X] + [(x, False) for x in RIB_FLOOR_X]:
        z_in = min(skin_z(x - RIB_T / 2.0, INNER_A, INNER_B),
                   skin_z(x + RIB_T / 2.0, INNER_A, INNER_B))
        if up:
            r = zbox(RIB_T, L + 2.0, z_in - RIB_H, OUTER_B + 1.0, x, 0.0)
        else:
            r = zbox(RIB_T, L + 2.0, -(OUTER_B + 1.0), -z_in + RIB_H, x, 0.0)
        r = r.intersect(clip)
        out = r if out is None else out.union(r)
    return out


def tube_bracing():
    """Every stiffener, as one solid, before it joins the tube (--tube, lozenge section)."""
    out = tube_ribs()
    for y in BAND_Y_TOP:
        out = out.union(tube_band(y))
    return out


def tube_screws():
    """[(x, z)] of the four end-plate screws, same at both ends (--tube)."""
    out = [(x, z) for (x, z, d) in tube_bosses()]
    for x in (TUBE_SCREW_X_BL, TUBE_SCREW_X_BR):
        floor = -skin_z(x, INNER_A, INNER_B)
        out.append((x, (floor + TUBE_RAIL_TOP) / 2.0))
    return out


def zcyl(d, z0, z1, x, y):
    return cq.Workplane("XY", origin=(x, y, z0)).circle(d / 2.0).extrude(z1 - z0)


def zbox(w, l, z0, z1, x, y):
    return (cq.Workplane("XY", origin=(x, y, z0))
            .box(w, l, z1 - z0, centered=(True, True, False)))


def ybore(d, x, z, y0, y1):
    return (cq.Workplane("XY", origin=(x, y0, z))
            .transformed(rotate=(-90, 0, 0))
            .circle(d / 2.0).extrude(y1 - y0))


def yrect(w, h, x, z, y0, y1):
    return (cq.Workplane("XY", origin=(x, y0, z))
            .transformed(rotate=(-90, 0, 0))
            .rect(w, h).extrude(y1 - y0))


def yfrustum(w0, h0, w1, h1, x, z, y0, y1):
    """A rectangular frustum along +Y: w0 x h0 at y0 lofted to w1 x h1 at y1."""
    return (cq.Workplane("XY", origin=(x, y0, z))
            .transformed(rotate=(-90, 0, 0))
            .rect(w0, h0).workplane(offset=y1 - y0).rect(w1, h1).loft(combine=True))


def halfspace(above, size=2000.0):
    z0 = 0.0 if above else -size
    return cq.Workplane("XY", origin=(0, 0, z0)).box(
        size, size, size, centered=(True, True, False))


def neutrik_cut(x, z, y0, y1, diag="nesw"):
    c = ybore(BORE_D, x, z, y0, y1)
    corners = ((+SCREW_OFF, -SCREW_OFF), (-SCREW_OFF, +SCREW_OFF)) if diag == "nesw" \
        else ((-SCREW_OFF, -SCREW_OFF), (+SCREW_OFF, +SCREW_OFF))
    for dx, dz in corners:
        c = c.union(ybore(SCREW_D, x + dx, z + dz, y0, y1))
    return c


# ===========================================================================
# Shell
# ===========================================================================
def shell_tube():
    tube = section_prism(OUTER_A, OUTER_B, OUTER_L).cut(
        section_prism(INNER_A, INNER_B, OUTER_L + 10.0))
    for sy in (-1, 1):
        y = sy * (OUTER_L / 2.0 - END_T / 2.0)
        tube = tube.cut(section_prism(OUTER_A - SKIN, OUTER_B - SKIN,
                                 END_T + 0.01, y))
    return tube


def tongue_ring(inset, width, height, length, clearance=0.0):
    a = inset - clearance
    b = inset + width + clearance
    ring = section_prism(INNER_A + b, INNER_B + b, length).cut(
        section_prism(INNER_A + a, INNER_B + a, length + 10.0))
    slab = cq.Workplane("XY").box(OUTER_A * 4, length, height * 2,
                                  centered=(True, True, False))
    return ring.intersect(slab)


# ===========================================================================
def build_bottom():
    part = shell_tube().intersect(halfspace(False))

    # --- PCB channel -------------------------------------------------------
    # Deep groove on the left (there is 22 mm of room there), shallower on the
    # right. The board goes in by pushing its left edge fully into the deep
    # groove, dropping the right edge past the shallow lip, then sliding back.
    # Rails stop short of the end rebates -- overrunning them by even 0.4 mm
    # puts the rail inside the end piece's own volume.
    rail_len = PCB_L
    if SECTION == "flat":
        # Open ledges, not grooves: the board rests on the ledge and is located sideways
        # by a riser outboard of each edge; the top shell's rails hold it down (see
        # HOLD_RAILS). Every face here is a step that prints floor-down with no overhang.
        # The riser is clipped half a wall INTO the flank, as the posts are, so the union
        # meets the shell with overlap rather than a shared face.
        for face, riser, sx in ((RAIL_L_FACE, RISER_L_FACE, -1),
                                (RAIL_R_FACE, RISER_R_FACE, +1)):
            outer = sx * (OUTER_A + 5.0)
            ledge = zbox(abs(outer - face), rail_len, Z_BOT_IN, Z_PCB_BOT,
                         (outer + face) / 2.0, Y_BOARD_OFF)
            wall = zbox(abs(outer - riser), rail_len, Z_BOT_IN, Z_PCB_TOP + CH_ABOVE,
                        (outer + riser) / 2.0, Y_BOARD_OFF)
            clip = section_prism(*POST_CLIP, OUTER_L + 10.0)
            part = part.union(ledge.intersect(clip)).union(wall.intersect(clip))
    else:
        for face, sx in ((RAIL_L_FACE, -1), (RAIL_R_FACE, +1)):
            outer = sx * (OUTER_A + 5.0)
            rail = zbox(abs(outer - face), rail_len, Z_BOT_IN, Z_PCB_TOP + CH_ABOVE,
                        (outer + face) / 2.0, Y_BOARD_OFF)
            part = part.union(rail.intersect(section_prism(INNER_A, INNER_B,
                                                           OUTER_L + 10.0)))
        # ONE slot, spanning root to root: it is the board's swept volume. Cutting
        # each rail outward from its own root instead would run straight through
        # the flank wall and open a slit down both sides of the case.
        part = part.cut(zbox(SLOT_R_ROOT - SLOT_L_ROOT, rail_len + 2.0,
                             Z_PCB_BOT, Z_PCB_BOT + CH_SLOT_H,
                             (SLOT_L_ROOT + SLOT_R_ROOT) / 2.0, Y_BOARD_OFF))

    # --- bolt posts --------------------------------------------------------
    for (x, y, d) in POSTS:
        part = part.union(zcyl(d, Z_BOT_IN - 2.0, 0.0, x, y)
                          .intersect(section_prism(*POST_CLIP, OUTER_L + 10.0)))
    for (x, y, d) in POSTS:
        part = part.cut(zcyl(INSERT_PILOT_D, -INSERT_DEPTH, 0.5, x, y))

    part = part.union(tongue_ring(TONGUE_INSET, TONGUE_W, TONGUE_H,
                                  OUTER_L - 2 * END_T - 2 * FIT))
    return part


def top_apertures(part):
    """The UI apertures and the guide tubes, on whichever part carries the top wall."""
    # Status LEDs: one window with a rebate for a smoked acrylic strip. A
    # printed body is opaque, so unlike the acrylic top plate in
    # docs/ENCLOSURE.md the LEDs need either this window or light pipes.
    led_x = bx(LED_X) + (TUBE_LED_SHIFT if TUBE else 0.0)
    led_y = by(sum(LED_Y) / len(LED_Y))
    part = part.cut(zbox(LED_WIN[0], LED_WIN[1], Z_TOP_IN - 1.0, OUTER_B + 5.0,
                         led_x, led_y))
    # Flat-floored rebate: the top face is curved, so the pocket floor is put
    # on a plane at the LOWEST point of the surface over the window. A flat
    # acrylic strip then seats without rocking and sits slightly proud-free.
    x_far = abs(led_x) + LED_WIN[0] / 2.0 + 1.5
    z_surf = skin_z(x_far)
    part = part.cut(zbox(LED_WIN[0] + 2 * 1.5, LED_WIN[1] + 2 * 1.5,
                         z_surf - LED_WIN_REBATE, OUTER_B + 5.0,
                         led_x, led_y))
    # Service pinholes, each with an internal guide tube down to the switch
    for y in BTN_Y:
        x, yy = bx(BTN_X), by(y)
        if TUBE:
            # Standing on its rear end, this boss lies on its side: a teardrop pointing
            # at the plate (-Y) and a fin under its apex, back to the wall.
            part = part.union(teardrop_zcyl(BTN_GUIDE_OD, BTN_GUIDE_Z0, Z_TOP_IN + 0.5,
                                            x, yy, point=-1))
            y_top = yy - BTN_GUIDE_OD / 2.0 * math.sqrt(2.0) + TUBE_FIN_BURY
            part = part.union(fin_yz(x, TUBE_FIN_T, y_top, BTN_GUIDE_Z0,
                                     Z_TOP_IN + 0.5))
        else:
            part = part.union(zcyl(BTN_GUIDE_OD, BTN_GUIDE_Z0, Z_TOP_IN + 0.5,
                                   x, yy))
    for y in BTN_Y:
        part = part.cut(zcyl(BTN_D, Z_PCB_TOP + 6.0, OUTER_B + 5.0,
                             bx(BTN_X), by(y)))
    # SW201 CAN terminator: screwdriver slot
    part = part.cut(zbox(DIP_SLOT[0], DIP_SLOT[1], Z_TOP_IN - 1.0, OUTER_B + 5.0,
                         bx(DIP_X), by(DIP_Y)))
    return part


def build_tube():
    """The one-piece body (--tube): the whole section, TUBE_L long, open at both ends."""
    L = TUBE_L
    part = section_prism(OUTER_A, OUTER_B, L).cut(
        section_prism(INNER_A, INNER_B, L + 10.0))
    clip = section_prism(*POST_CLIP, L + 10.0)

    # --- PCB channel: closed grooves both sides, rails the full length -------
    # The board comes in from the front along Y, so the grooves can be symmetric and
    # the rails run right to the end faces, where they also carry the lower screws.
    for face, sx in ((RAIL_L_FACE, -1), (RAIL_R_FACE, +1)):
        outer = sx * (OUTER_A + 5.0)
        rail = zbox(abs(outer - face), L + 2.0, Z_BOT_IN, TUBE_RAIL_TOP,
                    (outer + face) / 2.0, 0.0)
        part = part.union(rail.intersect(clip))
    part = part.cut(zbox(SLOT_R_ROOT - SLOT_L_ROOT, L + 4.0,
                         Z_PCB_BOT, Z_PCB_BOT + CH_SLOT_H,
                         (SLOT_L_ROOT + SLOT_R_ROOT) / 2.0, 0.0))

    # --- screw bosses under the top wall, full length -------------------------
    for (x, z, d) in tube_bosses():
        part = part.union(ybore(d, x, z, -L / 2.0 - 1.0, L / 2.0 + 1.0).intersect(clip))

    # --- internal bracing: hoop bands and longitudinal ribs --------------------
    if SECTION != "flat":
        part = part.union(tube_bracing())

    part = top_apertures(part)
    # The flush switch cover's pocket and lever notch. After the apertures, so the
    # pinholes and the SW201 slot come up through its floor.
    part = part.cut(sw_pocket_cut())

    # --- insert pilots at both ends of all four screw positions ---------------
    for (x, z) in tube_screws():
        part = part.cut(ybore(INSERT_PILOT_D, x, z, L / 2.0 - INSERT_DEPTH, L / 2.0 + 1.0))
        part = part.cut(ybore(INSERT_PILOT_D, x, z, -L / 2.0 - 1.0, -L / 2.0 + INSERT_DEPTH))

    # Everything that was built past the end faces (rails, bosses) is trimmed flush
    # in one cut, rather than trusting coplanar unions at both ends.
    return part.intersect(cq.Workplane("XY").box(4 * OUTER_A, L, 4 * OUTER_B))


def build_top():
    part = shell_tube().intersect(halfspace(True))

    part = part.cut(tongue_ring(TONGUE_INSET, TONGUE_W, TONGUE_H + 0.3,
                                OUTER_L - 2 * END_T, clearance=FIT))

    # No hold-down pads: the channel is a closed groove on both edges, and the
    # board's primary fixing is the SIX M3 panel screws that bolt its three
    # NE8FBH bodies to the front end piece. The channel supports and guides.

    part = top_apertures(part)

    # --- board hold-down (flat section) ------------------------------------
    # Rails from the lid down onto the board's edge strips, where the bottom shell's
    # open ledges cannot hold it. Top-face-down these are vertical walls rooted 1 mm
    # into the lid; nothing here is an overhang. They reach HOLD_GAP short of the
    # board so that, as with the posts, the parting faces and not the rails decide
    # when the case is closed.
    if SECTION == "flat":
        for side, spans in HOLD_RAILS.items():
            x0, x1 = HOLD_X[side]
            for y0, y1 in spans:
                part = part.union(zbox(x1 - x0, by(y1) - by(y0),
                                       Z_PCB_TOP + HOLD_GAP, Z_TOP_IN + 1.0,
                                       (x0 + x1) / 2.0, (by(y0) + by(y1)) / 2.0))

    # --- bolt posts --------------------------------------------------------
    # Build the posts down to the parting plane, THEN cut the gap back out. Starting the
    # cylinder at POST_GAP instead leaves it touching the shell only along a tangent curve,
    # and that union is not reliable -- it silently dropped the post at (-52.5, +35.25)
    # altogether, three of four surviving. Cutting is robust where that union is not.
    for (x, y, d) in POSTS:
        part = part.union(zcyl(d, 0.0, Z_TOP_IN + 2.0, x, y)
                          .intersect(section_prism(*POST_CLIP, OUTER_L + 10.0)))
    for (x, y, d) in POSTS:
        part = part.cut(zcyl(d + 0.4, -0.5, POST_GAP, x, y))
        part = part.cut(zcyl(SCREW_CLEAR_D, -0.5, OUTER_B + 5.0, x, y))
        # Pocket for a proud insert, cut from the post's own face upward.
        part = part.cut(zcyl(INSERT_RELIEF_D, POST_GAP - 0.01,
                             POST_GAP + INSERT_RELIEF_H, x, y))
        # One absolute floor for all four, so every head gets the same flat seat and one
        # screw length serves the case. The boss below Z_SEAT is what the counterbore is
        # cut from -- validate() checks it stays inside the boss and inside the flank.
        part = part.cut(zcyl(SCREW_HEAD_D, Z_SEAT, OUTER_B + 5.0, x, y))
    return part


def led_insert():
    """The LED window insert: tile in the rebate, four pillars down to the LEDs."""
    led_x = bx(LED_X) + (TUBE_LED_SHIFT if TUBE else 0.0)
    led_y = by(sum(LED_Y) / len(LED_Y))
    x_far = abs(led_x) + LED_WIN[0] / 2.0 + 1.5
    z_surf = skin_z(x_far)                      # the rebate floor is LED_WIN_REBATE below
    w = LED_WIN[0] + 2 * 1.5 - 2 * LED_INSERT_CLEAR
    l = LED_WIN[1] + 2 * 1.5 - 2 * LED_INSERT_CLEAR
    part = zbox(w, l, z_surf - LED_WIN_REBATE, z_surf, led_x, led_y)
    z_bot = Z_PCB_TOP + LED_0603_H + LED_PILLAR_GAP
    for y in LED_Y:
        part = part.union(zbox(LED_PILLAR[0], LED_PILLAR[1], z_bot,
                               z_surf - LED_WIN_REBATE + 0.5, led_x, by(y)))
    return part


def switch_cover_box():
    """Plan-view extent of the switch cover, board frame: (x0, x1, y0, y1)."""
    x0 = min(bx(BTN_X) - BTN_D / 2.0, bx(DIP_X) - DIP_SLOT[0] / 2.0) - SW_COVER_MARGIN
    x1 = max(bx(BTN_X) + BTN_D / 2.0, bx(DIP_X) + DIP_SLOT[0] / 2.0) + SW_COVER_MARGIN
    led_y = by(sum(LED_Y) / len(LED_Y))
    y0 = max(by(BTN_Y[0]) - BTN_D / 2.0 - SW_COVER_MARGIN,
             led_y + LED_WIN[1] / 2.0 + 1.5 + SW_COVER_LED_GAP)
    y1 = by(DIP_Y) + DIP_SLOT[1] / 2.0 + SW_COVER_MARGIN
    return x0, x1, y0, y1


def sw_plane():
    """The flush cover's top plane (--tube): z = z0 + slope * x, board frame.

    Through the lid's chord across the cover, lifted by half the chord's sag so the lid
    wanders +/- a quarter of it either side of the plane rather than all on one side.
    """
    x0, x1, _, _ = switch_cover_box()
    za, zb = skin_z(x0), skin_z(x1)
    slope = (zb - za) / (x1 - x0)
    xs = [x0 + (x1 - x0) * i / 40.0 for i in range(41)]
    sag = max(skin_z(x) - (za + slope * (x - x0)) for x in xs)
    return za - slope * x0 + sag / 2.0, slope


def sw_slab(z_lo, z_hi, pad=0.0):
    """Everything between two planes parallel to sw_plane(), offsets z_lo..z_hi from it,
    inside the cover footprint grown by pad (rounded corners), board frame."""
    x0, x1, y0, y1 = switch_cover_box()
    z0, slope = sw_plane()
    xc, yc = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    ang = math.degrees(math.atan(slope))
    slab = (cq.Workplane("XY").box(x1 - x0 + 2 * pad, y1 - y0 + 2 * pad, z_hi - z_lo,
                                   centered=(True, True, False))
            .edges("|Z").fillet(SW_COVER_R + pad)
            .translate((0, 0, z_lo))
            .rotate((0, 0, 0), (0, 1, 0), -ang)
            .translate((xc, yc, z0 + slope * xc)))
    return slab


def sw_notch(z_lo, z_hi):
    """The lever notch past the pocket's front (+y) end, same planes as sw_slab()."""
    x0, x1, y0, y1 = switch_cover_box()
    z0, slope = sw_plane()
    xc = (x0 + x1) / 2.0
    ang = math.degrees(math.atan(slope))
    # Overlaps the pocket by 1 mm so the two cuts share volume, not a face.
    ln = SW_NOTCH_L + SW_POCKET_CLEAR + 1.0
    return (cq.Workplane("XY").box(SW_NOTCH_W, ln, z_hi - z_lo, centered=(True, True, False))
            .edges("|Z").fillet(1.0)
            .translate((0, 0, z_lo))
            .rotate((0, 0, 0), (0, 1, 0), -ang)
            .translate((xc, y1 + SW_POCKET_CLEAR + SW_NOTCH_L - ln / 2.0, z0 + slope * xc)))


def sw_pocket_cut():
    """What the tube loses for the flush cover: the pocket and its lever notch."""
    return (sw_slab(-SW_POCKET_T, 5.0, pad=SW_POCKET_CLEAR)
            .union(sw_notch(-SW_POCKET_T, 5.0)))


def switch_cover_flush():
    """The tube's cover: a flat slab in the lid pocket, pegs and key below (--tube)."""
    x0, x1, y0, y1 = switch_cover_box()
    z0, slope = sw_plane()
    part = sw_slab(-SW_POCKET_T, 0.0)
    # Bevel under the front edge, over the notch: a wedge along the edge, cut away.
    # Built in the slab's own frame (front edge at y = hl, underside at z = -T), then
    # tilted and placed exactly as sw_slab() is. The triangle runs 0.5 mm past the edge
    # and the underside so the cut never ends on one of the slab's faces.
    ang = math.degrees(math.atan(slope))
    b, t, hl = SW_NOTCH_BEVEL, SW_POCKET_T, (y1 - y0) / 2.0
    xc, yc = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    wedge = (cq.Workplane("YZ")
             .polyline([(hl - b - 0.5, -t - 0.5), (hl + 0.5, -t - 0.5),
                        (hl + 0.5, -t + b + 0.5)]).close()
             .extrude(x1 - x0 + 2.0)
             .translate((-(x1 - x0) / 2.0 - 1.0, 0, 0))
             .rotate((0, 0, 0), (0, 1, 0), -ang)
             .translate((xc, yc, z0 + slope * xc)))
    part = part.cut(wedge)
    # Pegs and key rooted 0.5 mm up into the slab, a real overlap rather than a shared face.
    for y in BTN_Y:
        x = bx(BTN_X)
        zf = z0 + slope * x - SW_POCKET_T               # the pocket floor over this pinhole
        part = part.union(zcyl(SW_COVER_PEG_D, zf - SW_COVER_PEG_L, zf + 0.5, x, by(y)))
    x = bx(DIP_X)
    zf = min(z0 + slope * (x - DIP_SLOT[0] / 2.0), z0 + slope * (x + DIP_SLOT[0] / 2.0)) \
        - SW_POCKET_T
    part = part.union(zbox(DIP_SLOT[0] - 2 * SW_COVER_KEY_CLEAR,
                           DIP_SLOT[1] - 2 * SW_COVER_KEY_CLEAR,
                           zf - SW_COVER_KEY_FLUSH_L, zf + 0.5, x, by(DIP_Y)))
    return part


def switch_cover():
    """Cap over SW301/SW302's pinholes and SW201's slot: pegs in the pinholes hold it."""
    if TUBE:
        return switch_cover_flush()
    x0, x1, y0, y1 = switch_cover_box()
    xs = [x0 + (x1 - x0) * i / 40.0 for i in range(41)]
    z_hi = max(skin_z(x) for x in xs)
    z_lo = min(skin_z(x) for x in xs)
    part = (zbox(x1 - x0, y1 - y0, z_lo - 1.0, z_hi + SW_COVER_T,
                 (x0 + x1) / 2.0, (y0 + y1) / 2.0)
            .edges("|Z").fillet(SW_COVER_R))
    part = part.cut(section_prism(OUTER_A, OUTER_B, OUTER_L + 20.0))
    # Pegs and key rooted 0.5 mm up into the cap, a real overlap rather than a shared face.
    for y in BTN_Y:
        x = bx(BTN_X)
        zs = skin_z(x)
        part = part.union(zcyl(SW_COVER_PEG_D, zs - SW_COVER_PEG_L, zs + 0.5, x, by(y)))
    x = bx(DIP_X)
    zs = min(skin_z(x - DIP_SLOT[0] / 2.0), skin_z(x + DIP_SLOT[0] / 2.0))
    part = part.union(zbox(DIP_SLOT[0] - 2 * SW_COVER_KEY_CLEAR,
                           DIP_SLOT[1] - 2 * SW_COVER_KEY_CLEAR,
                           zs - SW_COVER_KEY_L, zs + 0.5, x, by(DIP_Y)))
    return part


def build_end(kind):
    if TUBE:
        # A flush plate on the tube's end, screwed to it: full outer outline, full
        # END_T, and four clearance holes over the bosses' insert pilots.
        part = section_prism(OUTER_A, OUTER_B, END_T)
        for (x, z) in tube_screws():
            part = part.cut(ybore(SCREW_CLEAR_D, x, z, -END_T, END_T))
    else:
        part = section_prism(OUTER_A - SKIN - FIT, OUTER_B - SKIN - FIT, END_T - 0.2)
    y0, y1 = -END_T, END_T
    # The rear piece faces the cavity with its +Y side: it is placed at -Y in the assembly
    # and the board lies at +Y of it. So its inner face is at +t/2, its outer at -t/2.
    t = END_T if TUBE else END_T - 0.2
    y_in, y_out = t / 2.0, -t / 2.0
    if kind == "front":
        # ALL THREE the same way round. J201, J202 and J401 are placed identically on
        # the board (all rot=180, identical pads), so their flange screw holes are on the
        # same diagonal -- alternating the middle one was simply wrong, and the middle
        # connector would not take its two panel screws.
        for x in ETHERCON_X:
            part = part.cut(neutrik_cut(bx(x), Z_AXIS, y0, y1, diag=ETHERCON_DIAG))
    else:
        # The USB-C step: a well standing inward off the plate, its floor USBC_WELL_GAP
        # behind the board edge, the plug aperture through that floor. Built as a solid
        # block rooted 0.5 mm INTO the plate (a real overlap, not a shared face), then
        # hollowed from the outside, then pierced.
        x, z, w = bx(USBC_X), USBC_ZC, USBC_WELL_WALL
        y_floor = y_in + USBC_WELL_DEPTH             # the floor's inner face
        part = part.union(yrect(USBC_WELL_W + 2 * w, USBC_WELL_H + 2 * w, x, z,
                                y_in - 0.5, y_floor))
        # The cavity, then a 45-degree funnel from the cavity down to the aperture. Printed
        # outer face down the floor is the TOP of the well, and a flat floor's inner ring
        # would be perimeters laid over air; the funnel carries every floor line on the one
        # below it, and steers a plug nose onto the aperture into the bargain.
        taper = (USBC_WELL_W - USBC_PLUG_W) / 2.0
        part = part.cut(yrect(USBC_WELL_W, USBC_WELL_H, x, z,
                              y_out - 1.0, y_floor - w - taper))
        part = part.cut(yfrustum(USBC_WELL_W, USBC_WELL_H, USBC_PLUG_W, USBC_PLUG_H, x, z,
                                 y_floor - w - taper, y_floor - w))
        part = part.cut(yrect(USBC_PLUG_W, USBC_PLUG_H, x, z, y_out - 1.0, y_floor + 1.0))
        # 45-degree lead-in at the outer face: the port is 7 mm down a blind hole, and a
        # plug wants to be funnelled into it. Runs one chamfer OUTSIDE the face so the
        # cut never shares a face with the plate.
        c = USBC_WELL_CHAMFER
        part = part.cut(yfrustum(USBC_WELL_W + 4 * c, USBC_WELL_H + 4 * c,
                                 USBC_WELL_W, USBC_WELL_H, x, z, y_out - c, y_out + c))
    return part


# ===========================================================================
# Lettering
# ===========================================================================
def text_page(txt, cap, font, u, v_base, h):
    """txt on the page, centred on u, baseline at v_base, h tall in +z."""
    w = cq.Workplane("XY").text(txt, cap / CAP_EM, h, fontPath=str(font),
                                halign="left", valign="bottom")
    bb = w.val().BoundingBox()
    return w.translate((u - (bb.xmin + bb.xmax) / 2.0, v_base, 0))


def mark_page(width, u, v_top, h):
    """The traced mark on the page, width wide, centred on u, its top edge at v_top.

    The trace is a set of rings -- bow-tie, stoat outline, the islands inside it -- and
    which are ink and which are paper is even-odd by nesting. Largest first, so every
    ring's container is already in place when it is added or cut.
    """
    doc = json.loads(MARK_FILE.read_text())
    pw, ph = doc["source"]["size"]
    s = width / pw
    rings = [r[:-1] if r[0] == r[-1] else r
             for f in doc["features"] for r in f["geometry"]["coordinates"]]

    def area(r):
        return abs(sum(x0 * y1 - x1 * y0
                       for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1]))) / 2.0

    def contains(r, p):
        x, y, n = p[0], p[1], False
        for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1]):
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                n = not n
        return n

    rings.sort(key=area, reverse=True)
    out = None
    for i, r in enumerate(rings):
        depth = sum(1 for big in rings[:i] if contains(big, r[0]))
        pts = [(u + (x - pw / 2.0) * s, v_top - (ph - y) * s) for x, y in r]   # y is up
        prism = cq.Workplane("XY").polyline(pts).close().extrude(h)
        if out is None:
            out = prism
        elif depth % 2 == 0:
            out = out.union(prism)
        else:
            out = out.cut(prism)
    return out, ph * s


def lid_layout(h):
    """The lid's page: mark, STOATWORKS / LABS, name. Returns (stamp, page u of its centre).

    Built about its own centre, v = 0; the caller puts that centre on the clear part of
    the top face.
    """
    mark_h = MARK_W * 602.0 / 778.0
    total = (mark_h + LID_GAPS[0] + 2 * WORD_CAP + WORD_LEAD + LID_GAPS[1]
             + NAME_CAP * 1.29)                     # the name's 'y' descends 0.29 cap
    v = total / 2.0
    stamp, _ = mark_page(MARK_W, 0.0, v, h)
    v -= mark_h + LID_GAPS[0] + WORD_CAP
    stamp = stamp.union(text_page("STOATWORKS", WORD_CAP, FONT_XBOLD, 0.0, v, h))
    v -= WORD_LEAD + WORD_CAP
    stamp = stamp.union(text_page("LABS", WORD_CAP, FONT_XBOLD, 0.0, v, h))
    v -= LID_GAPS[1] + NAME_CAP
    stamp = stamp.union(text_page(NAME, NAME_CAP, FONT_BOLD, 0.0, v, h))
    return stamp


def lid_openings():
    """Board-frame x extents of every top-face opening: (x0, x1, y0, y1) rectangles."""
    led_x = bx(LED_X) + (TUBE_LED_SHIFT if TUBE else 0.0)
    led_y = by(sum(LED_Y) / len(LED_Y))
    rw, rl = LED_WIN[0] + 3.0, LED_WIN[1] + 3.0
    out = [(led_x - rw / 2, led_x + rw / 2, led_y - rl / 2, led_y + rl / 2)]
    for y in BTN_Y:
        r = BTN_GUIDE_OD / 2.0
        out.append((bx(BTN_X) - r, bx(BTN_X) + r, by(y) - r, by(y) + r))
    out.append((bx(DIP_X) - DIP_SLOT[0] / 2, bx(DIP_X) + DIP_SLOT[0] / 2,
                by(DIP_Y) - DIP_SLOT[1] / 2, by(DIP_Y) + DIP_SLOT[1] / 2))
    if not TUBE:
        for (x, y, d) in POSTS:
            r = SCREW_HEAD_D / 2.0
            out.append((x - r, x + r, y - r, y + r))
    else:
        # the flush cover's pocket, and the lever notch past its front end
        x0, x1, y0, y1 = switch_cover_box()
        c = SW_POCKET_CLEAR
        out.append((x0 - c, x1 + c, y0 - c, y1 + c + SW_NOTCH_L))
    return out


def lettering_cuts():
    """{part name: solid to cut} in the BOARD frame, plus the lid layout's placement."""
    h = 10.0
    d = LETTER_DEPTH
    cuts = {}

    # --- the lid -------------------------------------------------------------
    # Clear band of the top face: right of the openings, left of where the curve drops.
    x_l = max(o[1] for o in lid_openings() if o[0] < 0.0) + LID_CLEAR
    xc = (x_l + LID_RIGHT) / 2.0                        # board frame
    lid = lid_layout(OUTER_B + 5.0).val()               # from z 0 up through the lid
    # Physical frame: the page's u runs to -X (read from the etherCON end, your right
    # is -X), v to -Y (away from you). xDir -X with normal +Z gives exactly that.
    plane = cq.Plane(origin=(-xc, 0.0, 0.0), xDir=(-1, 0, 0), normal=(0, 0, 1))
    lid = cq.Workplane("XY").add(lid.moved(cq.Location(plane))).mirror("YZ")
    # Same depth everywhere, following the lid's curve: the band between the section d
    # inside the outer one and a section 1 mm OUTSIDE it. The cutter must not end on the
    # lid's own surface -- a cut whose face is coincident with the part's drops glyphs
    # (the tangency trap at POST_CLIP, again); past the surface is air anyway. The
    # exact-depth band is kept only to measure what the cut should remove.
    def band(outside):
        return section_prism(OUTER_A + outside, OUTER_B + outside, OUTER_L + 10.0).cut(
            section_prism(OUTER_A - d, OUTER_B - d, OUTER_L + 20.0)).intersect(
            halfspace(True))
    cuts["canary_tube" if TUBE else "canary_shell_top"] = (
        lid.intersect(band(1.0)), lid.intersect(band(0.0)))

    # --- the end plates --------------------------------------------------------
    # Each plate is built centred on y = 0, outer face at +t/2 (front) or -t/2 (rear).
    t = END_T if TUBE else END_T - 0.2
    front = None
    for x, label in zip(ETHERCON_X, PORT_LABELS):
        # physical x of the connector is -bx(x); read from outside the front, u = -X
        s = text_page(label, PORT_CAP, FONT_BOLD, bx(x), PORT_LABEL_Z - PORT_CAP / 2.0, h)
        front = s if front is None else front.union(s)
    plane = cq.Plane(origin=(0.0, t / 2.0 - d, 0.0), xDir=(-1, 0, 0), normal=(0, 1, 0))
    cuts["canary_end_front"] = (cq.Workplane("XY")
                                  .add(front.val().moved(cq.Location(plane)))
                                  .mirror("YZ"))
    # Read from outside the rear, u = +X; the USB-C is at physical x -bx(USBC_X).
    z_base = USBC_ZC + USBC_WELL_H / 2.0 + 2 * USBC_WELL_CHAMFER + USB_LABEL_GAP
    rear = text_page(USB_LABEL, PORT_CAP, FONT_BOLD, -bx(USBC_X), z_base, h)
    plane = cq.Plane(origin=(0.0, -(t / 2.0 - d), 0.0), xDir=(1, 0, 0), normal=(0, -1, 0))
    cuts["canary_end_rear"] = (cq.Workplane("XY")
                                 .add(rear.val().moved(cq.Location(plane)))
                                 .mirror("YZ"))
    # Trim each plate's stamp to run from depth d to 1 mm out into the air (not flush with
    # the face, for the same reason as the lid), and keep the exact-depth slab to measure.
    for name in ("canary_end_front", "canary_end_rear"):
        sy = 1 if name.endswith("front") else -1

        def slab(outside):
            return (cq.Workplane("XY").box(4 * OUTER_A, d + outside, 4 * OUTER_B)
                    .translate((0, sy * (t / 2.0 - d / 2.0 + outside / 2.0), 0)))
        cuts[name] = (cuts[name].intersect(slab(1.0)), cuts[name].intersect(slab(0.0)))
    return cuts, (x_l, xc)


def apply_lettering(parts):
    """Engrave every face, then prove each engraving landed wholly in material.

    A label that ran into an opening, or off the edge of a plate, would cut less than
    its own volume -- so each cut must be (almost) all inside the part it is cut from,
    and the part must lose exactly that much and keep its bounding box.
    """
    errs = []
    cuts, (x_l, xc) = lettering_cuts()
    for name, (cut, exact) in cuts.items():
        part = parts[name]
        v_cut = exact.val().Volume()                # what the lettering should remove
        v_in = part.intersect(cut).val().Volume()   # what it will remove
        if v_cut < 1.0:
            errs.append(f"{name}: lettering is empty ({v_cut:.2f} mm3)")
            continue
        if abs(v_in - v_cut) > 0.03 * v_cut:
            errs.append(f"{name}: {v_in:.1f} of {v_cut:.1f} mm3 of lettering is in "
                        f"material -- it runs into an opening or off the face")
        after = part.cut(cut)
        b0, b1 = part.val().BoundingBox(), after.val().BoundingBox()
        if max(abs(getattr(b0, k) - getattr(b1, k))
               for k in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")) > 0.01:
            errs.append(f"{name}: lettering changed the bounding box")
        # Measured in a box around the lettering, not as whole-part volumes: OCC integrates
        # these spline-sectioned parts hundreds of mm3 differently from one boolean to the
        # next, which swamps a 24 mm3 label. Locally the numbers agree to 0.01 mm3.
        cb = cut.val().BoundingBox()
        near = cq.Solid.makeBox(cb.xlen + 2.0, cb.ylen + 2.0, cb.zlen + 2.0,
                                cq.Vector(cb.xmin - 1.0, cb.ymin - 1.0, cb.zmin - 1.0))
        lost = part.val().intersect(near).Volume() - after.val().intersect(near).Volume()
        if abs(lost - v_in) > 0.01 * v_in + 0.05:
            errs.append(f"{name}: lost {lost:.1f} mm3 to {v_in:.1f} mm3 of lettering")
        if not after.val().isValid() or len(after.val().Solids()) != 1:
            errs.append(f"{name}: not one valid solid after lettering")
        parts[name] = after
    bb = cuts["canary_tube" if TUBE else "canary_shell_top"][1].val().BoundingBox()
    # in the board frame; the mirror on export changes no distance
    for (x0, x1, y0, y1) in lid_openings():
        if (bb.xmin < x1 + LID_CLEAR - 0.01 and bb.xmax > x0 - LID_CLEAR + 0.01
                and bb.ymin < y1 + LID_CLEAR and bb.ymax > y0 - LID_CLEAR):
            errs.append(f"lid lettering (x {bb.xmin:.1f}..{bb.xmax:.1f}) comes within "
                        f"{LID_CLEAR} mm of an opening at x {x0:.1f}..{x1:.1f}")
    if bb.xmax > LID_RIGHT + 0.01:
        errs.append(f"lid lettering reaches x {bb.xmax:.1f}, past LID_RIGHT {LID_RIGHT}")
    cx0, cx1, cy0, cy1 = switch_cover_box()
    if bb.xmin < cx1 + 0.5 and bb.xmax > cx0 and bb.ymin < cy1 and bb.ymax > cy0:
        errs.append(f"the switch cover (x {cx0:.1f}..{cx1:.1f}) would hide the lid "
                    f"lettering (x {bb.xmin:.1f}..)")
    note = (f"lettering {LETTER_DEPTH} mm deep: lid {bb.xlen:.0f} x {bb.ylen:.0f} mm "
            f"(board x {bb.xmin:.1f}..{bb.xmax:.1f}), "
            f"{' / '.join(PORT_LABELS)} under the etherCONs, {USB_LABEL} over the USB-C")
    return errs, note


# ===========================================================================
def validate():
    errs, notes = [], []

    if END_T >= B_SERIES_PANEL_MAX:
        errs.append(f"end piece {END_T} mm is at or over the B-series "
                    f"{B_SERIES_PANEL_MAX} mm panel thickness")

    if abs((GAP_L - GAP_R) - 2 * (PCB_W / 2.0 - ETHERCON_X[1])) > 0.01:
        errs.append("GAP_L - GAP_R does not centre the etherCON cluster")
    if abs((GAP_L + PCB_W + GAP_R) - 2 * INNER_A) > 0.01:
        errs.append(f"GAP_L + board + GAP_R = {GAP_L + PCB_W + GAP_R} != "
                    f"internal width {2 * INNER_A}")

    # Every point the section must contain
    checks = [("board right edge", X_PCB_R, Z_PCB_BOT),
              ("board left edge", X_PCB_L, Z_PCB_BOT),
              ("etherCON plate top corner",
               bx(ETHERCON_X[-1]) + NE8FBH_PLATE_W / 2.0,
               Z_AXIS + NE8FBH_PLATE_ABOVE),
              ("etherCON plate bottom corner",
               bx(ETHERCON_X[0]) - NE8FBH_PLATE_W / 2.0,
               Z_AXIS - NE8FBH_PLATE_BELOW)]
    for what, x, z in checks:
        if not inside(x, z, INNER_A, INNER_B):
            errs.append(f"{what} ({x:.1f}, {z:.1f}) falls outside the section")

    if BORE_D / 2.0 + SCREW_D / 2.0 > math.hypot(SCREW_OFF, SCREW_OFF):
        errs.append("Neutrik screw holes break into the bore")

    # The six M3 panel screws are the board's primary fixing, so the plate has to
    # LAND on the end piece's inner face. The board is free to slide in Y inside
    # its channel, so what matters is that the shift needed is available, not that
    # the nominal position is exact.
    panel_y = by(ETHERCON_Y + NE8FBH_PANEL_FROM_ORIGIN)
    end_inner = OUTER_L / 2.0 - END_T
    shift = end_inner - panel_y
    slack = end_inner - (PCB_L / 2.0 + Y_BOARD_OFF)   # board front edge -> end piece
    if shift < -0.01:
        errs.append(f"etherCON panel plane sits {-shift:.2f} mm PAST the end "
                    f"piece -- the connector fouls it before the board is home")
    elif shift > slack + 0.01:
        errs.append(f"etherCON panel plane is {shift:.2f} mm short of the end "
                    f"piece but the board can only travel {slack:.2f} mm")
    else:
        notes.append(f"etherCON plate lands on the end piece with the board "
                     f"{shift:.2f} mm forward of centre ({slack:.2f} mm available)")

    if NE8FBH_PIN_BELOW_PCB > PCB_UNDER:
        errs.append(f"etherCON pins hang {NE8FBH_PIN_BELOW_PCB:.2f} mm below the "
                    f"board, into the {PCB_UNDER:.1f} mm underfloor space")
    else:
        notes.append(f"etherCON pins hang {NE8FBH_PIN_BELOW_PCB:.2f} mm below the "
                     f"board -- {PCB_UNDER - NE8FBH_PIN_BELOW_PCB:.2f} mm to the floor")

    pitch = ETHERCON_X[1] - ETHERCON_X[0]
    if pitch < NE8FBH_PLATE_W + 1.0:
        errs.append(f"etherCON pitch {pitch} mm leaves no gap between plates")
    else:
        notes.append(f"etherCON pitch {pitch:.0f} mm -> "
                     f"{pitch - NE8FBH_PLATE_W:.0f} mm between front plates")

    for (x, y, d) in (() if TUBE else POSTS):
        if X_PCB_L - d / 2.0 < x < X_PCB_R + d / 2.0:
            errs.append(f"bolt post at x={x:.1f} overlaps the board")
        if not inside(x + d / 2.0, 0.0, INNER_A, INNER_B):
            errs.append(f"bolt post at x={x:.1f} breaks through the flank")
        if abs(y) + d / 2.0 > INNER_L / 2.0 - END_T:
            errs.append(f"bolt post at y={y:.1f} fouls the end rebate")

        # The counterbore only produces a FLAT seat where it actually cuts material, so
        # Z_SEAT has to sit below the outer skin right across the head, at the outboard
        # edge as well as on axis. This is the check the old fixed-depth counterbore
        # failed silently on the right-hand pair.
        edge = abs(x) + SCREW_HEAD_D / 2.0
        if Z_SEAT >= skin_z(edge):
            errs.append(f"counterbore floor {Z_SEAT:.2f} is above the skin "
                        f"({skin_z(edge):.2f}) at the outboard edge of the post at "
                        f"x={x:+.1f} -- that head would bear on the curve, not a seat")
        if SCREW_HEAD_D > d:
            errs.append(f"counterbore {SCREW_HEAD_D} is wider than the {d} boss "
                        f"at x={x:+.1f}")
        if not inside(edge, Z_SEAT, OUTER_A, OUTER_B):
            errs.append(f"counterbore at x={x:+.1f} breaks out of the flank at "
                        f"z={Z_SEAT:.2f}")
        # The insert pocket is cut into the BOTTOM shell's post, which the inner profile
        # clips: the post is only as tall as the cavity is deep at that x.
        post_h = skin_z(abs(x), INNER_A, INNER_B)
        if INSERT_DEPTH > post_h - 2.0:
            errs.append(f"insert pocket {INSERT_DEPTH} mm leaves under 2 mm of post "
                        f"below it at x={x:+.1f} (post is {post_h:.2f} mm)")

    if not TUBE:
        seats = {round(Z_SEAT, 2)}
        notes.append(f"all four heads seat on one flat at z {Z_SEAT:.1f} "
                     f"({len(seats)} seat height, so one screw length)")
        fits = [L for L in (16, 18, 20, 22, 25, 30) if SCREW_MIN <= L <= SCREW_MAX]
        notes.append(f"screw window {SCREW_MIN:.1f}-{SCREW_MAX:.1f} mm -> stock lengths "
                     f"{', '.join('M3 x %d' % L for L in fits) if fits else 'NONE'}")
        if not fits:
            errs.append("no stock screw length falls in the usable window")

    ui_depth = Z_TOP_IN - Z_PCB_TOP
    notes.append(f"board sits {ui_depth:.1f} mm below the top face -- SW301 (EN) "
                 f"and SW302 (BOOT) are guided {BTN_D:.1f} mm tool pinholes, "
                 f"SW201 a screwdriver slot")
    rebate_y = OUTER_L / 2.0 - END_T
    if not TUBE:
        if abs(Y_BOARD_OFF) + PCB_L / 2.0 > rebate_y:
            errs.append(f"channel rails overrun the end-piece rebate "
                        f"({abs(Y_BOARD_OFF) + PCB_L / 2.0:.2f} > {rebate_y:.2f})")
        if (OUTER_L - 2 * END_T - 2 * FIT) / 2.0 > rebate_y:
            errs.append("parting tongue overruns the end-piece rebate")
    for name, root in (("left", SLOT_L_ROOT), ("right", SLOT_R_ROOT)):
        if abs(root) > INNER_A - 2.0:
            errs.append(f"{name} groove root breaks through the flank wall")
    if not TUBE and SLOT_L_ROOT > X_PCB_L - CH_ENGAGE_R:
        errs.append("left groove is too shallow for the board to be entered")
    notes.append(f"LED window insert: {LED_WIN[0] + 3.0:.1f} x "
                 f"{LED_WIN[1] + 3.0:.1f} x {LED_WIN_REBATE:.1f} mm smoked acrylic")
    if TUBE:
        notes.append(f"board channel: closed grooves {CH_ENGAGE_R} mm both sides, "
                     f"{SLOT_R_ROOT - SLOT_L_ROOT - PCB_W:.1f} mm of side play -- the board "
                     f"slides in from the front, rear edge first")
        notes.append(f"screws: 8 x M3 x 8 button head through the end plates into "
                     f"{INSERT_LEN:.0f} mm inserts ({END_T:.1f} mm plate + {INSERT_LEN:.0f} "
                     f"insert = {END_T + INSERT_LEN:.1f} of 8, pocket {INSERT_DEPTH:.1f})")
        notes.append(f"inserts: 8 x M3 x {INSERT_LEN:.0f} heat-set, OD <= 4.2 for the "
                     f"{INSERT_PILOT_D} mm pilot, four in each end face")
    elif SECTION == "flat":
        notes.append(f"board channel: open ledges {CH_ENGAGE_L + LEDGE_CLEAR:.1f} mm "
                     f"(left) and {CH_ENGAGE_R + LEDGE_CLEAR:.1f} mm (right) wide, riser "
                     f"{LEDGE_CLEAR} mm outboard of each edge -- the board drops straight in")
    else:
        notes.append(f"board channel: left groove {CH_ENGAGE_L} mm, right "
                     f"{CH_ENGAGE_R} mm -- insert left edge first, then drop right")
    if not TUBE:
        notes.append(f"screws: 4 x M3 x 25 socket cap (reach {SCREW_REACH:.1f} mm, then "
                     f"{25 - SCREW_REACH:.1f} mm past the seat into a {INSERT_LEN:.0f} mm "
                     f"insert in a {INSERT_DEPTH:.1f} mm pocket)")
        notes.append(f"inserts: 4 x M3 x {INSERT_LEN:.0f} heat-set, OD <= 4.2 for the "
                     f"{INSERT_PILOT_D} mm pilot")

    # ---- the ESP32's antenna overhang ------------------------------------
    ant_y = by(ESP32_Y - ESP32_BODY_L / 2.0)    # rearmost point of the module
    ant_clear = ant_y - Y_IN_R
    if ant_clear < 0.5:
        errs.append(f"ESP32 module overhangs to y={ant_y:.2f}, only {ant_clear:.2f} mm "
                    f"clear of the rear face at {Y_IN_R:.2f} -- the antenna fouls it")
    else:
        notes.append(f"ESP32 antenna overhangs the board by {ESP32_OVERHANG:.2f} mm and "
                     f"clears the rear end piece by {ant_clear:.2f} mm")
    for lbl, x in (("left", bx(ESP32_X) - ESP32_BODY_W / 2.0),
                   ("right", bx(ESP32_X) + ESP32_BODY_W / 2.0)):
        if not inside(x, Z_PCB_TOP + 3.1, INNER_A, INNER_B):
            errs.append(f"ESP32 {lbl} edge ({x:.1f}) falls outside the section")

    # ---- USB-C: the rear plate steps in to meet the receptacle --------------
    if USBC_PLUG_W < USBC_W or USBC_PLUG_H < USBC_H:
        errs.append(f"USB-C aperture {USBC_PLUG_W} x {USBC_PLUG_H} is smaller than the "
                    f"receptacle {USBC_W} x {USBC_H}")
    frame = min(USBC_WELL_W - USBC_PLUG_W, USBC_WELL_H - USBC_PLUG_H) / 2.0
    if frame < 1.2:
        errs.append(f"USB-C well floor is only {frame:.2f} mm wide around the aperture")
    if abs((USBC_WELL_W - USBC_PLUG_W) - (USBC_WELL_H - USBC_PLUG_H)) > 0.01:
        errs.append("USB-C well-to-aperture step differs in W and H -- the funnel under "
                    "the floor is only 45 deg if they match")
    if USBC_WELL_CHAMFER > USBC_WELL_WALL:
        errs.append("USB-C lead-in chamfer is deeper than the well wall is thick")
    if USBC_WELL_GAP < 0.5:
        errs.append(f"USB-C well floor is {USBC_WELL_GAP} mm from the board edge")
    if USBC_WELL_DEPTH < USBC_WELL_WALL + 1.0:
        errs.append("USB-C well is shallower than its own floor")
    ux, uz = bx(USBC_X), USBC_ZC
    ow, oh = USBC_WELL_W + 2 * USBC_WELL_WALL, USBC_WELL_H + 2 * USBC_WELL_WALL
    ea, eb = (OUTER_A, OUTER_B) if TUBE else (OUTER_A - SKIN - FIT, OUTER_B - SKIN - FIT)
    for sx in (-1, 1):
        for sz in (-1, 1):
            cx, cz = ux + sx * ow / 2.0, uz + sz * oh / 2.0
            # the well's outline on the plate, with a wall's worth of plate around it...
            if not inside(cx, cz, ea - 1.0, eb - 1.0):
                errs.append(f"USB-C well corner ({cx:.1f}, {cz:.1f}) breaks out of the "
                            f"end piece")
            # ...and inside the cavity it projects into, clear of the shell's inner skin
            if not inside(cx, cz, INNER_A - 0.5, INNER_B - 0.5):
                errs.append(f"USB-C well corner ({cx:.1f}, {cz:.1f}) meets the shell "
                            f"inside the case")
    if not TUBE and uz + oh / 2.0 > -0.3:
        errs.append(f"USB-C well reaches z={uz + oh / 2.0:.2f}, the parting plane")
    if TUBE:
        if ux + ow / 2.0 > RAIL_R_FACE - 1.0:
            errs.append(f"USB-C well ({ux + ow / 2.0:.1f}) meets the right rail "
                        f"({RAIL_R_FACE:.1f}) it stands beside")
    else:
        # the well spans the last REAR_CLEAR of the cavity, where the rear posts are
        post_edge = POST_X_R - BOSS_D_R / 2.0
        if ux + ow / 2.0 > post_edge - 1.0:
            errs.append(f"USB-C well ({ux + ow / 2.0:.1f}) meets the rear-right post "
                        f"({post_edge:.1f})")
    notes.append(f"USB-C: rear plate steps in {USBC_WELL_DEPTH:.1f} mm to "
                 f"{USBC_WELL_GAP:.1f} mm behind the board edge; well "
                 f"{USBC_WELL_W:.1f} x {USBC_WELL_H:.1f}, floor aperture "
                 f"{USBC_PLUG_W:.0f} x {USBC_PLUG_H:.0f} centred z {uz:.2f}; a moulding "
                 f"that cannot pass the floor stops "
                 f"{USBC_WELL_WALL + USBC_WELL_GAP:.1f} mm from the mouth")

    # ---- the posts must not decide whether the case closes ----------------
    if TUBE:
        pass
    elif INSERT_RELIEF_D >= min(BOSS_D_L, BOSS_D_R):
        errs.append(f"insert relief {INSERT_RELIEF_D} leaves no face on the "
                    f"{min(BOSS_D_L, BOSS_D_R)} boss")
    if INSERT_RELIEF_D <= SCREW_CLEAR_D:
        errs.append("insert relief is no wider than the screw clearance hole")
    if POST_GAP <= 0.0:
        errs.append("POST_GAP is zero -- the posts close the case, not the parting faces")
    else:
        annulus = (min(BOSS_D_L, BOSS_D_R) - INSERT_RELIEF_D) / 2.0
        notes.append(f"post relief: {POST_GAP:.1f} mm gap at the parting plane, plus a "
                     f"{INSERT_RELIEF_D:.1f} x {INSERT_RELIEF_H:.1f} mm pocket for a proud "
                     f"insert ({annulus:.2f} mm of face left on the smaller boss)")

    # minimum wall around the section
    if SECTION == "flat":
        # Uniform by construction (see box_r); what can go wrong is the inner radius
        # collapsing, which would put a sharp internal corner under the outer fillet.
        r_in = box_r(INNER_A)
        if r_in < 1.0:
            errs.append(f"inner fillet {r_in:.2f} mm -- BOX_R is smaller than the wall")
        notes.append(f"flat section: R{BOX_R:.0f} edges with a "
                     f"{box_ch(BOX_R):.1f} mm tangent chamfer; wall {WALL} mm uniform, "
                     f"first layer {2 * (OUTER_A - box_ch(BOX_R)):.0f} x {OUTER_L:.0f} mm "
                     f"flat on the plate")
    else:
        worst = min(
            math.hypot(*(a - b for a, b in zip(p, q)))
            for p, q in zip(se_points(INNER_A, INNER_B, 90),
                            se_points(OUTER_A, OUTER_B, 90)))
        if worst < WALL * 0.75:
            errs.append(f"section wall thins to {worst:.2f} mm (nominal {WALL})")
        else:
            notes.append(f"minimum section wall {worst:.2f} mm")

    # ---- flat section: the hold-down rails ---------------------------------
    if SECTION == "flat":
        # Worst case the board sits hard against the far riser, which moves the rail
        # LEDGE_CLEAR further onto the board; the courtyard nearest that edge has to
        # clear rail width plus twice that slack, with 0.4 mm to spare.
        reach = 2 * LEDGE_CLEAR + HOLD_W
        for side, keep in (("left", EDGE_KEEPOUT_L), ("right", EDGE_KEEPOUT_R)):
            if reach > keep - 0.4:
                errs.append(f"{side} hold-down rail reaches {reach:.2f} mm onto the "
                            f"board but a courtyard starts at {keep:.2f} mm")
        win_c = sum(LED_Y) / len(LED_Y)
        win_y0, win_y1 = win_c - LED_WIN[1] / 2.0, win_c + LED_WIN[1] / 2.0
        for y0, y1 in HOLD_RAILS["left"]:
            if y0 < win_y1 + 0.3 and y1 > win_y0 - 0.3:
                errs.append(f"left hold-down rail y {y0}..{y1} runs through the LED "
                            f"window (y {win_y0:.1f}..{win_y1:.1f})")
        rebate_y = OUTER_L / 2.0 - END_T
        for side, spans in HOLD_RAILS.items():
            x0, x1 = HOLD_X[side]
            for y0, y1 in spans:
                if by(y1) > rebate_y + 0.01 or by(y0) < -rebate_y - 0.01:
                    errs.append(f"{side} hold-down rail y {y0}..{y1} overruns an end "
                                f"rebate")
                # the tubes, the posts and the slot all live on the top shell too
                for yy in BTN_Y:
                    if (by(y0) - BTN_GUIDE_OD / 2.0 < by(yy) < by(y1) + BTN_GUIDE_OD / 2.0
                            and x0 - BTN_GUIDE_OD / 2.0 < bx(BTN_X) < x1 + BTN_GUIDE_OD / 2.0):
                        errs.append(f"{side} hold-down rail meets a guide tube")
                for (px, py, d) in POSTS:
                    if (x0 - d / 2.0 < px < x1 + d / 2.0
                            and by(y0) - d / 2.0 < py < by(y1) + d / 2.0):
                        errs.append(f"{side} hold-down rail meets the post at "
                                    f"({px:+.1f}, {py:+.1f})")
        for side, riser in (("left", RISER_L_FACE), ("right", RISER_R_FACE)):
            gap = min(abs(riser - HOLD_X[side][0]), abs(riser - HOLD_X[side][1]))
            if gap < 0.5:
                errs.append(f"{side} hold-down rail is {gap:.2f} mm from the riser")
        tip = Z_PCB_TOP + HOLD_GAP
        notes.append(f"flat section: board on open ledges, held down by "
                     f"{sum(len(s) for s in HOLD_RAILS.values())} rails from the lid "
                     f"({HOLD_W} mm wide, tip {HOLD_GAP} mm above the board at "
                     f"z {tip:.1f}); guide tubes reach z {BTN_GUIDE_Z0:.1f}")

    # ---- one-piece tube: screws, bosses, fins ------------------------------
    if TUBE:
        rp = INSERT_PILOT_D / 2.0
        plate_x = bx(ETHERCON_X[-1]) + NE8FBH_PLATE_W / 2.0      # etherCON plates reach
        for (x, z) in tube_screws():
            # The screw (and its pilot) must sit in material: inside the section at
            # every edge of the pilot, and clear of the cavity where the boss is.
            for dx, dz in ((rp, 0), (-rp, 0), (0, rp), (0, -rp)):
                if not inside(x + dx, z + dz, OUTER_A - 1.0, OUTER_B - 1.0):
                    errs.append(f"pilot at ({x:+.1f}, {z:+.1f}) breaks out of the "
                                f"section")
            if abs(x) < plate_x + SCREW_CLEAR_D / 2.0 + 1.0 and z > Z_AXIS - NE8FBH_PLATE_BELOW - 2.0:
                errs.append(f"screw at ({x:+.1f}, {z:+.1f}) lands on an etherCON plate")
            ow = USBC_WELL_W + 2 * USBC_WELL_WALL
            oh = USBC_WELL_H + 2 * USBC_WELL_WALL
            if (abs(x - bx(USBC_X)) < ow / 2.0 + SCREW_CLEAR_D / 2.0 + 1.0
                    and abs(z - USBC_ZC) < oh / 2.0 + SCREW_CLEAR_D / 2.0 + 1.0):
                errs.append(f"screw at ({x:+.1f}, {z:+.1f}) meets the USB-C well")
        for (x, z) in tube_screws()[2:]:
            # lower pilots: inside their rail block, clear of the groove
            floor = -skin_z(x, INNER_A, INNER_B)
            wall = min(z - rp - floor, TUBE_RAIL_TOP - (z + rp))
            if wall < 1.5:
                errs.append(f"lower pilot at x={x:+.1f} leaves {wall:.2f} mm of rail "
                            f"above or below it")
            if x > 0 and x - rp < SLOT_R_ROOT + 0.8:
                errs.append(f"right lower pilot breaks into the groove")
            if x < 0 and x + rp > SLOT_L_ROOT - 0.8:
                errs.append(f"left lower pilot breaks into the groove")
        for (x, z, d) in tube_bosses():
            if z - d / 2.0 < Z_PCB_TOP + 3.5 and X_PCB_L - d / 2.0 < x < X_PCB_R + d / 2.0:
                errs.append(f"top boss at x={x:+.1f} reaches down to z={z - d / 2.0:.1f} "
                            f"over the board")
            if not inside(x + d / 2.0, z, INNER_A + WALL / 2.0, INNER_B + WALL / 2.0):
                errs.append(f"top boss at x={x:+.1f} is outside the wall")
        # the fins: root along the top wall, clear of the LED window and the DIP slot
        led_x = bx(LED_X) + TUBE_LED_SHIFT
        wx0, wx1 = led_x - LED_WIN[0] / 2.0, led_x + LED_WIN[0] / 2.0
        wy_c = by(sum(LED_Y) / len(LED_Y))
        wy0, wy1 = wy_c - LED_WIN[1] / 2.0, wy_c + LED_WIN[1] / 2.0
        dx0, dx1 = bx(DIP_X) - DIP_SLOT[0] / 2.0, bx(DIP_X) + DIP_SLOT[0] / 2.0
        dy0, dy1 = by(DIP_Y) - DIP_SLOT[1] / 2.0, by(DIP_Y) + DIP_SLOT[1] / 2.0
        fx0, fx1 = bx(BTN_X) - TUBE_FIN_T / 2.0, bx(BTN_X) + TUBE_FIN_T / 2.0
        reach = (Z_TOP_IN + 0.5) - BTN_GUIDE_Z0
        for y in BTN_Y:
            y_top = by(y) - BTN_GUIDE_OD / 2.0 * math.sqrt(2.0) + TUBE_FIN_BURY
            fy0, fy1 = y_top - reach, y_top
            if fx0 < wx1 + 0.3 and fx1 > wx0 - 0.3 and fy0 < wy1 + 0.3 and fy1 > wy0 - 0.3:
                errs.append(f"guide-tube fin (x {fx0:.1f}..{fx1:.1f}, y {fy0:.1f}..{fy1:.1f}) "
                            f"runs into the LED window (x {wx0:.1f}..{wx1:.1f}, "
                            f"y {wy0:.1f}..{wy1:.1f})")
            if fx0 < dx1 + 0.3 and fx1 > dx0 - 0.3 and fy0 < dy1 + 0.3 and fy1 > dy0 - 0.3:
                errs.append(f"guide-tube fin runs into the SW201 slot")
            if fy0 < Y_IN_R + 1.0:
                errs.append(f"guide-tube fin reaches the rear end face")
        notes.append(f"tube: {TUBE_L:.1f} mm body, end plates {END_T:.1f} mm on the ends, "
                     f"LED window at x {led_x:+.1f} (shifted {TUBE_LED_SHIFT:+.1f}); "
                     f"guide tubes teardrop + {TUBE_FIN_T} mm fin, "
                     f"{fx0 - wx1:.2f} mm right of the window")
    if TUBE:
        # The flush cover: how far its flat top strays from the curved lid, and how much
        # wall the pocket leaves under it at its thinnest.
        x0, x1, y0, y1 = switch_cover_box()
        z0, slope = sw_plane()
        c = SW_POCKET_CLEAR
        xs = [x0 - c + (x1 - x0 + 2 * c) * i / 60.0 for i in range(61)]
        stray = max(abs(z0 + slope * x - skin_z(x)) for x in xs)
        floor = min(z0 + slope * x - SW_POCKET_T - skin_z(x, INNER_A, INNER_B) for x in xs)
        if stray > 0.1:
            errs.append(f"flush switch cover strays {stray:.2f} mm from the lid")
        if floor < SW_POCKET_FLOOR_MIN:
            errs.append(f"switch-cover pocket leaves {floor:.2f} mm of wall "
                        f"(< {SW_POCKET_FLOOR_MIN})")
        if BTN_GUIDE_Z0 < Z_TOP_IN + 0.5 and min(z0 + slope * bx(BTN_X) - SW_POCKET_T,
                                                 99.0) < Z_TOP_IN + 0.5:
            errs.append("switch-cover pocket floor is below the guide tubes' tops")
        notes.append(f"switch cover sits flush: {x1 - x0:.1f} x {y1 - y0:.1f} x "
                     f"{SW_POCKET_T:.1f} mm slab tilted {math.degrees(math.atan(slope)):.1f} "
                     f"deg to the lid (within {stray:.2f} mm of it), {floor:.2f} mm of wall "
                     f"under the pocket, {SW_NOTCH_W:.0f} x {SW_NOTCH_L:.1f} mm lever notch "
                     f"at its front end")
    return errs, notes


def probe(solid, x, y, z0, z1, d=1.0):
    """Volume of a small cylinder intersected with a built solid, in mm3."""
    try:
        return solid.intersect(zcyl(d, z0, z1, x, y)).val().Volume()
    except Exception:
        return 0.0


def verify_rear_well(part):
    """Probe the rear plate's USB-C step, in the part's own frame (plate centred on y=0).

    Four things can go wrong silently: the well body fails to union (a tangent contact,
    as the posts once did), the cavity or the aperture fails to cut, or the chamfer cut
    takes the plate with it. So: material in a wall, air in the cavity, material in the
    floor, air through the aperture.
    """
    errs = []
    t = END_T if TUBE else END_T - 0.2
    x, z, w = bx(USBC_X), USBC_ZC, USBC_WELL_WALL
    y_in = t / 2.0
    y_floor = y_in + USBC_WELL_DEPTH
    y_mid = (y_in + y_floor - w) / 2.0
    if probe(part, x + USBC_WELL_W / 2.0 + w / 2.0, y_mid, z - 2.0, z + 2.0, d=0.8) < 0.5:
        errs.append("rear plate has no USB-C well wall")
    if probe(part, x, y_mid, z - 2.0, z + 2.0, d=0.8) > 0.05:
        errs.append("rear plate's USB-C well is not hollow")
    fx = x + (USBC_PLUG_W + USBC_WELL_W) / 4.0
    if probe(part, fx, y_floor - w / 2.0, z - 1.0, z + 1.0, d=0.6) < 0.2:
        errs.append("rear plate's USB-C well has no floor")
    if probe(part, x, y_floor - w / 2.0, z - 1.0, z + 1.0, d=0.8) > 0.05:
        errs.append("rear plate's USB-C floor aperture is not open")
    # the plate itself survived the chamfer, a wall's width outside the well
    if probe(part, x + USBC_WELL_W / 2.0 + w + 1.0, 0.0, z - 1.0, z + 1.0, d=0.6) < 0.2:
        errs.append("rear plate is missing beside the USB-C well")
    bb = part.val().BoundingBox()
    if abs(bb.ymax - y_floor) > 0.01:
        errs.append(f"rear plate reaches y={bb.ymax:.2f}, expected the well floor at "
                    f"{y_floor:.2f}")
    return errs


def verify_led_insert(part):
    errs = []
    led_x = bx(LED_X) + (TUBE_LED_SHIFT if TUBE else 0.0)
    z_bot = Z_PCB_TOP + LED_0603_H + LED_PILLAR_GAP
    bb = part.val().BoundingBox()
    if abs(bb.zmin - z_bot) > 0.01:
        errs.append(f"LED insert pillars end at z={bb.zmin:.2f}, expected {z_bot:.2f}")
    for y in LED_Y:
        if probe(part, led_x, by(y), z_bot + 1.0, z_bot + 4.0, d=0.6) < 0.1:
            errs.append(f"LED insert has no pillar over D30x at board y={y}")
    # the pillars stay inside the window opening, with clearance
    if LED_PILLAR[0] > LED_WIN[0] - 1.0:
        errs.append("LED pillars are wider than the window")
    if by(LED_Y[-1]) + LED_PILLAR[1] / 2.0 > by(sum(LED_Y) / len(LED_Y)) + LED_WIN[1] / 2.0 - 0.5 \
            or by(LED_Y[0]) - LED_PILLAR[1] / 2.0 < by(sum(LED_Y) / len(LED_Y)) - LED_WIN[1] / 2.0 + 0.5:
        errs.append("LED pillars run past the window's ends")
    return errs


def verify_switch_cover(parts):
    errs = []
    cover = parts["canary_switch_cover"]
    body = parts["canary_tube" if TUBE else "canary_shell_top"]
    x0, x1, y0, y1 = switch_cover_box()
    for y in BTN_Y:
        x, zs = bx(BTN_X), skin_z(bx(BTN_X))
        if probe(cover, x, by(y), zs - SW_COVER_PEG_L + 0.5, zs - 0.5, d=1.0) < 0.5:
            errs.append(f"switch cover has no peg in the pinhole at board y={y}")
    x = bx(DIP_X)
    if TUBE:
        z0, slope = sw_plane()
        zf = z0 + slope * x - SW_POCKET_T
        if probe(cover, x, by(DIP_Y), zf - SW_COVER_KEY_FLUSH_L + 0.2, zf - 0.2,
                 d=1.0) < 0.2:
            errs.append("switch cover has no key in the SW201 slot")
        errs += verify_flush_pocket(cover, body)
    elif probe(cover, x, by(DIP_Y), skin_z(x) - SW_COVER_KEY_L + 0.3, skin_z(x) - 0.3,
               d=1.0) < 0.2:
        errs.append("switch cover has no key in the SW201 slot")
    # It must sit ON the lid, not in it: nothing of the cap but its pegs and key may
    # share volume with the body.
    try:
        clash = cover.intersect(body).val().Volume()
    except Exception:
        clash = 0.0
    if clash > 0.05:
        errs.append(f"switch cover overlaps the body by {clash:.2f} mm3 -- "
                    f"a peg or the key does not fit its hole")
    for (ox0, ox1, oy0, oy1) in lid_openings()[:1]:
        if y0 < oy1 and x0 < ox1 and x1 > ox0:
            errs.append("switch cover runs over the LED rebate")
    return errs


def verify_flush_pocket(cover, tube):
    """The tube's pocket is open, floored, notched; the cover fills it and has its bevel."""
    errs = []
    x0, x1, y0, y1 = switch_cover_box()
    z0, slope = sw_plane()
    zp = lambda x: z0 + slope * x                   # the cover's top plane
    t = SW_POCKET_T
    # Sample points inside the footprint but clear of the pinholes and the slot.
    xm = (x0 + x1) / 2.0
    pts = [(x0 + 1.5, y0 + 1.5), (x1 - 1.5, y0 + 1.5), (x1 - 1.5, y1 - 1.5),
           (x0 + 1.5, y1 - 1.5)]
    for (x, y) in pts:
        if probe(tube, x, y, zp(x) - t + 0.15, zp(x) - 0.15, d=0.6) > 0.02:
            errs.append(f"pocket is not open at ({x:+.1f}, {y:+.1f})")
        if probe(tube, x, y, zp(x) - t - 0.8, zp(x) - t - 0.2, d=0.6) < 0.05:
            errs.append(f"pocket has no floor at ({x:+.1f}, {y:+.1f})")
        if probe(cover, x, y, zp(x) - t + 0.15, zp(x) - 0.15, d=0.6) < 0.05:
            errs.append(f"cover is missing at ({x:+.1f}, {y:+.1f})")
    # the notch: open to the floor past the front end, and wall either side of it
    yn = y1 + SW_POCKET_CLEAR + SW_NOTCH_L / 2.0
    if probe(tube, xm, yn, zp(xm) - t + 0.15, zp(xm) - 0.15, d=0.6) > 0.02:
        errs.append("lever notch is not open")
    xs = xm + SW_NOTCH_W / 2.0 + 1.0
    if probe(tube, xs, yn, zp(xs) - t + 0.15, zp(xs) - 0.3, d=0.6) < 0.05:
        errs.append("lever notch is wider than it should be (no wall beside it)")
    # the bevel: no cover at the front edge's bottom corner, cover just above it
    if probe(cover, xm, y1 - 0.15, zp(xm) - t, zp(xm) - t + 0.3, d=0.2) > 0.001:
        errs.append("cover has no bevel over the lever notch")
    if probe(cover, xm, y1 - 0.15, zp(xm) - 0.3, zp(xm) - 0.05, d=0.2) < 0.001:
        errs.append("the bevel took the whole front edge")
    return errs


def verify_bracing(tube):
    """The bands and ribs are in the built tube, and the stiffeners on their own stay out
    of every path and part that has to pass through or sit in the tube."""
    errs = []
    L = TUBE_L
    brace = tube_bracing()

    def clash(region):
        try:
            return brace.intersect(region).val().Volume()
        except Exception:
            return 0.0
    keep_out = {
        # the board slides in from the front: its pins below, its components and the guide
        # tubes' lower ends above, full length
        "the board's path": zbox(X_PCB_R - X_PCB_L, L + 4.0,
                                 Z_PCB_BOT - NE8FBH_PIN_BELOW_PCB - 0.5, BTN_GUIDE_Z0,
                                 (X_PCB_L + X_PCB_R) / 2.0, 0.0),
        # the etherCON plates enter from the front with the board
        "the etherCON plates' path": zbox(bx(ETHERCON_X[2]) - bx(ETHERCON_X[0])
                                          + NE8FBH_PLATE_W + 1.0, L + 4.0, Z_PCB_TOP,
                                          Z_AXIS + NE8FBH_PLATE_ABOVE + 1.0,
                                          bx(ETHERCON_X[1]), 0.0),
        # the rear plate's USB-C well, standing into the rear of the tube
        "the USB-C well": yrect(USBC_WELL_W + 2 * USBC_WELL_WALL + 2.0,
                                USBC_WELL_H + 2 * USBC_WELL_WALL + 2.0, bx(USBC_X), USBC_ZC,
                                -L / 2.0 - 1.0, -L / 2.0 + USBC_WELL_DEPTH + 1.0),
    }
    x0, x1, y0, y1 = opening_strip()
    keep_out["the lid's opening strip"] = zbox(x1 - x0 - 0.2, y1 - y0 - 0.2, 5.0,
                                               OUTER_B + 5.0, (x0 + x1) / 2.0,
                                               (y0 + y1) / 2.0)
    for (x, z) in tube_screws():
        for s in (-1, 1):
            keep_out[f"the pilot at ({x:+.1f}, {z:+.1f})"] = ybore(
                INSERT_PILOT_D + 2.0, x, z, s * L / 2.0 - s * (INSERT_DEPTH + 1.0),
                s * L / 2.0 + s * 1.0)
    for name, region in keep_out.items():
        v = clash(region)
        if v > 0.05:
            errs.append(f"bracing runs into {name} ({v:.1f} mm3)")
    # present where it should be, in the built tube
    for y_top in BAND_Y_TOP:
        yp = y_top - BAND_W / 2.0
        for (x, zlo, zhi, where) in ((0.0, -INNER_B + 0.3, -INNER_B + BAND_D - 0.3, "floor"),
                                     (0.0, INNER_B - BAND_D + 0.3, INNER_B - 0.3, "lid"),
                                     (INNER_A - BAND_D + 0.3, -1.0, 1.0, "right flank")):
            if probe(tube, x + (0.0 if where != "right flank" else 0.6), yp, zlo, zhi,
                     d=0.6) < 0.05:
                errs.append(f"band at y {y_top:+.1f} is missing at the {where}")
        # the 45-degree underside: at the band's foot, only the outermost sliver is band
        y_lo, _ = band_span(y_top)
        if probe(tube, 0.0, y_lo + 0.3, -INNER_B + 0.6, -INNER_B + BAND_D, d=0.4) > 0.01:
            errs.append(f"band at y {y_top:+.1f} has no chamfer under it")
    for x in RIB_TOP_X:
        z = skin_z(x, INNER_A, INNER_B)
        if probe(tube, x, 20.0, z - RIB_H + 0.3, z - 0.3, d=0.6) < 0.05:
            errs.append(f"lid rib at x {x:+.1f} is missing")
    for x in RIB_FLOOR_X:
        z = -skin_z(x, INNER_A, INNER_B)
        if probe(tube, x, 20.0, z + 0.3, z + RIB_H - 0.3, d=0.6) < 0.05:
            errs.append(f"floor rib at x {x:+.1f} is missing")
    return errs


def verify_solids(parts):
    """Check the BUILT solids, not the parameters.

    validate() proves the numbers agree; it cannot see a boolean that silently did
    nothing. One did: unioning a post that met the shell only along a tangent curve
    dropped the post at (-52.5, +35.25) from the top shell entirely and still wrote a
    valid, manifold, plausible-looking STL. Three posts out of four is not something a
    dimension check finds, so probe for material where material is supposed to be.
    """
    errs = []
    if TUBE:
        return verify_tube(parts)
    bot, top = parts["canary_shell_bottom"], parts["canary_shell_top"]
    for (x, y, d) in POSTS:
        # Off-axis, so the probe misses the insert pilot and the screw clearance bore
        # but stays inside the boss.
        px = x + (INSERT_PILOT_D / 2.0 + d / 2.0) / 2.0
        if probe(bot, px, y, -5.0, -1.0) < 0.5:
            errs.append(f"bottom shell has no post at ({x:+.1f}, {y:+.1f})")
        z0 = POST_GAP + INSERT_RELIEF_H + 0.5
        if probe(top, px, y, z0, Z_SEAT - 1.0) < 0.5:
            errs.append(f"top shell has no post at ({x:+.1f}, {y:+.1f})")
        # ...and check the relief is actually open, or the case still will not close.
        if probe(top, px, y, 0.05, POST_GAP - 0.05) > 0.05:
            errs.append(f"top shell post at ({x:+.1f}, {y:+.1f}) still reaches the "
                        f"parting plane -- POST_GAP was not cut")

    tb = top.val().BoundingBox()
    bb = bot.val().BoundingBox()
    if SECTION == "flat":
        # Each shell prints on its OUTER face, so that face has to be the flat it was
        # built as, and the top shell's lowest point is the hold-down rails, nothing else.
        if abs(tb.zmax - OUTER_B) > 0.01 or abs(bb.zmin + OUTER_B) > 0.01:
            errs.append(f"shells do not reach the flat faces (top {tb.zmax:.2f}, "
                        f"bottom {bb.zmin:.2f}, expected +/-{OUTER_B})")
        tip = Z_PCB_TOP + HOLD_GAP
        if abs(tb.zmin - tip) > 0.01:
            errs.append(f"top shell's lowest point is z={tb.zmin:.2f}, expected the "
                        f"hold-down rails at {tip:.2f}")
        # The rails exist where HOLD_RAILS says, and the bottom ledges are OPEN -- no
        # lip survived above them -- with a riser outboard of each edge.
        for side, spans in HOLD_RAILS.items():
            x0, x1 = HOLD_X[side]
            for y0, y1 in spans:
                if probe(top, (x0 + x1) / 2.0, (by(y0) + by(y1)) / 2.0,
                         tip + 0.5, tip + 8.0, d=0.8) < 0.5:
                    errs.append(f"top shell has no {side} hold-down rail over "
                                f"y {y0}..{y1}")
        for side, face, riser in (("left", RAIL_L_FACE, RISER_L_FACE),
                                  ("right", RAIL_R_FACE, RISER_R_FACE)):
            xm = (face + riser) / 2.0
            if probe(bot, xm, Y_BOARD_OFF, Z_BOT_IN + 1.0, Z_PCB_BOT - 0.5) < 0.5:
                errs.append(f"bottom shell has no {side} ledge")
            if probe(bot, xm, Y_BOARD_OFF, Z_PCB_BOT + 0.1, Z_PCB_TOP + CH_ABOVE + 3.0) > 0.05:
                errs.append(f"bottom shell's {side} ledge is closed over -- a lip "
                            f"survived above the board")
            xr = riser + (-1.0 if side == "left" else 1.0)
            if probe(bot, xr, Y_BOARD_OFF, Z_PCB_TOP, Z_PCB_TOP + CH_ABOVE - 0.5) < 0.3:
                errs.append(f"bottom shell has no {side} riser")
    else:
        # Nothing crosses the parting plane. Each shell prints on that face, so anything
        # that pokes through it becomes the part's lowest point and lifts the whole rim off
        # the plate. The guide tubes did exactly that.
        if tb.zmin < -0.01:
            errs.append(f"top shell reaches z={tb.zmin:.2f}, below the parting plane -- "
                        f"it will not print on its rim")
    # tongue_ring() builds its slab height*2 tall, so the tongue is really 2*TONGUE_H
    # (3.0 mm, into a 3.6 mm groove). It has always been so and it closes; measured here
    # rather than assumed from the constant.
    if bb.zmax > 2 * TONGUE_H + 0.01:
        errs.append(f"bottom shell reaches z={bb.zmax:.2f}, above its tongue")

    errs += verify_rear_well(parts["canary_end_rear"])
    errs += verify_led_insert(parts["canary_led_insert"])
    errs += verify_switch_cover(parts)
    for name, solid in parts.items():
        if not solid.val().isValid():
            errs.append(f"{name} is not a valid solid (OCC BRepCheck)")
    return errs


def verify_tube(parts):
    """verify_solids() for the one-piece body: probe what the tube has to carry."""
    errs = []
    tube = parts["canary_tube"]
    L = TUBE_L
    bb = tube.val().BoundingBox()
    if abs(bb.ymin + L / 2.0) > 0.01 or abs(bb.ymax - L / 2.0) > 0.01:
        errs.append(f"tube runs y {bb.ymin:.2f}..{bb.ymax:.2f}, not +/-{L / 2.0:.2f} -- "
                    f"something was not trimmed flush with the end faces")
    if abs(bb.zmax - OUTER_B) > 0.01 or abs(bb.zmin + OUTER_B) > 0.01:
        errs.append(f"tube is z {bb.zmin:.2f}..{bb.zmax:.2f}, expected +/-{OUTER_B}")
    rp = INSERT_PILOT_D / 2.0
    for (x, z) in tube_screws():
        for s in (-1, 1):
            ye = s * (L / 2.0 - 2.0)               # 2 mm in from each end face
            # the pilot is open...
            if probe(tube, x, ye, z - 0.3, z + 0.3, d=1.0) > 0.02:
                errs.append(f"pilot at ({x:+.1f}, {z:+.1f}) is not open at y={ye:+.1f}")
            # ...and has material around it, 1 mm outside the pilot wall
            for dx, dz in ((rp + 1.0, 0), (-(rp + 1.0), 0), (0, rp + 1.0), (0, -(rp + 1.0))):
                if probe(tube, x + dx, ye, z + dz - 0.3, z + dz + 0.3, d=0.6) < 0.05:
                    errs.append(f"no material beside the pilot at ({x:+.1f}, {z:+.1f}), "
                                f"y={ye:+.1f}, offset ({dx:+.1f}, {dz:+.1f})")
    for (x, z, d) in tube_bosses():
        if probe(tube, x + d / 2.0 - 0.8, 0.0, z - 0.3, z + 0.3, d=0.6) < 0.05:
            errs.append(f"top boss at x={x:+.1f} is missing mid-length")
    # the grooves are open along their whole length, both sides
    for name, xg in (("left", X_PCB_L + 0.5), ("right", X_PCB_R - 0.5)):
        for yy in (-L / 2.0 + 1.0, 0.0, L / 2.0 - 1.0):
            if probe(tube, xg, yy, Z_PCB_BOT + 0.3, Z_PCB_BOT + CH_SLOT_H - 0.3, d=0.6) > 0.02:
                errs.append(f"{name} groove is blocked at y={yy:+.1f}")
        if probe(tube, xg, 0.0, Z_PCB_BOT + CH_SLOT_H + 0.3, TUBE_RAIL_TOP - 0.3, d=0.6) < 0.05:
            errs.append(f"{name} groove has no lip over it")
    # guide tubes and their fins
    for y in BTN_Y:
        x, yy = bx(BTN_X), by(y)
        if probe(tube, x + 2.5, yy, BTN_GUIDE_Z0 + 1.0, BTN_GUIDE_Z0 + 4.0, d=0.6) < 0.05:
            errs.append(f"guide tube at y={yy:+.1f} is missing near its free end")
        if probe(tube, x, yy, BTN_GUIDE_Z0 + 1.0, BTN_GUIDE_Z0 + 4.0, d=0.6) > 0.02:
            errs.append(f"guide tube at y={yy:+.1f} has no bore")
        y_top = yy - BTN_GUIDE_OD / 2.0 * math.sqrt(2.0) + TUBE_FIN_BURY
        # A point on the fin 6 mm below its top, near the wall -- unless that lands in
        # the NEXT tube down, whose body then carries this one (the two are 10 mm
        # apart and the upper teardrop's apex overlaps the lower circle).
        yp = y_top - 6.0
        if all(abs(yp - by(y2)) > BTN_GUIDE_OD / 2.0 + 1.0 for y2 in BTN_Y if y2 != y):
            if probe(tube, x, yp, Z_TOP_IN - 8.0, Z_TOP_IN - 5.0, d=0.5) < 0.02:
                errs.append(f"guide-tube fin at y={yy:+.1f} is missing")
    for name in ("canary_end_front", "canary_end_rear"):
        e = parts[name]
        eb = e.val().BoundingBox()
        if abs(eb.xlen - 2 * OUTER_A) > 0.3 or abs(eb.zlen - 2 * OUTER_B) > 0.3:
            errs.append(f"{name} outline {eb.xlen:.1f} x {eb.zlen:.1f} is not the tube's "
                        f"{2 * OUTER_A:.1f} x {2 * OUTER_B:.1f}")
        for (x, z) in tube_screws():
            if probe(e, x, 0.0, z - 0.3, z + 0.3, d=1.0) > 0.02:
                errs.append(f"{name} has no screw hole at ({x:+.1f}, {z:+.1f})")
    if SECTION != "flat":
        errs += verify_bracing(tube)
    errs += verify_rear_well(parts["canary_end_rear"])
    errs += verify_led_insert(parts["canary_led_insert"])
    errs += verify_switch_cover(parts)
    for name, solid in parts.items():
        if not solid.val().isValid():
            errs.append(f"{name} is not a valid solid (OCC BRepCheck)")
    return errs


def mesh_leaks(path):
    """'' if the exported STL is watertight, else why not. Needs trimesh; silent without.

    A valid OCC solid can still tessellate to a non-manifold mesh where two of its faces
    are coincident -- the post/inner-surface seam did, 458 open edges -- and the slicer
    will repair that however it likes. orient_for_print.py warns; this refuses.
    """
    try:
        import trimesh
    except ImportError:
        return ""
    m = trimesh.load(str(path))
    if m.is_watertight:
        return ""
    import collections
    cnt = collections.Counter(map(tuple, m.edges_sorted))
    bad = sum(1 for v in cnt.values() if v != 2)
    return f"is not watertight: {bad} open/non-manifold edges"


def main():
    errs, notes = validate()
    print(f"CANary printable enclosure -- {SECTION} section"
          + (", one-piece tube" if TUBE else ""))
    notes.append(f"LED insert: {LED_WIN[0] + 3 - 2 * LED_INSERT_CLEAR:.1f} x "
                 f"{LED_WIN[1] + 3 - 2 * LED_INSERT_CLEAR:.1f} x {LED_WIN_REBATE:.1f} tile, "
                 f"four {LED_PILLAR[0]:.0f} x {LED_PILLAR[1]:.0f} pillars to "
                 f"{LED_PILLAR_GAP:.1f} mm above the LEDs -- print it tile-down in natural "
                 f"or white PLA")
    print(f"  internal   {2 * INNER_A:.0f} x {INNER_L:.0f} x {2 * INNER_B:.0f} mm  "
          + (f"(flat top/bottom, R{BOX_R:.0f} edges)" if SECTION == "flat"
             else f"(superellipse n={SE_N:.0f})"))
    print(f"  external   {2 * OUTER_A:.0f} x {OUTER_L:.0f} x {2 * OUTER_B:.0f} mm")
    for n in notes:
        print(f"  - {n}")
    for e in errs:
        print(f"  ! {e}")
    if errs:
        print("\nGEOMETRY VALIDATION FAILED -- nothing written")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    if TUBE:
        parts = {
            "canary_tube": build_tube(),
            "canary_end_front": build_end("front"),
            "canary_end_rear": build_end("rear"),
            "canary_led_insert": led_insert(),
            "canary_switch_cover": switch_cover(),
        }
    else:
        parts = {
            "canary_shell_bottom": build_bottom(),
            "canary_shell_top": build_top(),
            "canary_end_front": build_end("front"),
            "canary_end_rear": build_end("rear"),
            "canary_led_insert": led_insert(),
            "canary_switch_cover": switch_cover(),
        }
    solid_errs = verify_solids(parts)
    if solid_errs:
        for e in solid_errs:
            print(f"  ! {e}")
        print("\nBUILT-SOLID VERIFICATION FAILED -- nothing written")
        return 1
    # Last, so every probe above ran on the plain parts; lettering is only ever skin deep.
    letter_errs, letter_note = apply_lettering(parts)
    for e in letter_errs:
        print(f"  ! {e}")
    if letter_errs:
        print("\nLETTERING VERIFICATION FAILED -- nothing written")
        return 1
    print(f"  - {letter_note}")
    if MIRROR:
        # Into the physical, right-handed world: see the note at MIRROR. Verification
        # above ran in the board frame; the mirror changes no distance.
        parts = {k: v.mirror("YZ") for k, v in parts.items()}
        print("  mirrored about YZ on export (KiCad's frame is left-handed)")
    else:
        print("  NOT mirrored (--as-kicad): these match the pre-2026-09-21 prints")

    for name in sorted(parts):
        solid = parts[name]
        cq.exporters.export(solid, str(OUT / f"{name}.step"))
        cq.exporters.export(solid, str(OUT / f"{name}.stl"),
                            tolerance=0.01, angularTolerance=0.1)
        leak = mesh_leaks(OUT / f"{name}.stl")
        if leak:
            print(f"  ! {name}.stl {leak}")
            return 1
        bb = solid.val().BoundingBox()
        vol = solid.val().Volume() / 1000.0
        print(f"  {name:26s} {bb.xlen:6.1f} x {bb.ylen:6.1f} x {bb.zlen:5.1f} mm"
              f"  {vol:6.1f} cm3  ~{vol * 1.07:4.0f} g")

    asm = cq.Assembly()
    # the end pieces sit in pockets (two shells) or on the end faces (tube); either
    # way their centres are END_T/2 inside the overall length
    for name, solid in parts.items():
        loc = cq.Location(cq.Vector(0, 0, 0))
        if name.endswith("end_front"):
            loc = cq.Location(cq.Vector(0, +(OUTER_L / 2.0 - END_T / 2.0), 0))
        elif name.endswith("end_rear"):
            loc = cq.Location(cq.Vector(0, -(OUTER_L / 2.0 - END_T / 2.0), 0))
        asm.add(solid, name=name, loc=loc)
    asm.export(str(OUT / "canary_case_assembly.step"))
    print(f"  wrote {len(parts)} parts + canary_case_assembly.step -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
