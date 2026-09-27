"""Print variants for the CANary case.

One nozzle change covers both materials actually to hand: Bambu ships an ABS-GF profile
for the H2C only at 0.4, and PLA is happy there too, so 0.4 is the nozzle to fit.

`absgf-0.4-dualsupport` is the default and the one to print. It differs from `absgf-0.4`
only in where the support goes: onto the H2C\'s second nozzle, in Bambu Support for ABS,
hard against the model. `absgf-0.4` is kept as the single-spool fallback for when there
is no support spool on the shelf -- it prints, but the supports come out of the shells
by force.

`asa-0.6` remains the design spec from 3dp/README.md and is kept so the numbers in that
file stay reproducible -- it is not the one to print unless there is ASA on the shelf.

`absgf-0.4-flat` is a different CASE, not a different process: the flat-section
geometry from `gen_case_3dp.py --flat`, whose shells print outer face down and need no
support at all. Its `geometry` key tells build.sh to take the STLs from print-flat/.
One filament, one nozzle, no support spool.

`absgf-0.4-tube` is the one-piece body from `gen_case_3dp.py --tube`, printed standing
on its rear end with the two end plates beside it (print-tube/, three parts). Nothing on
it overhangs -- the guide tubes carry their own fins -- so it too is one filament and no
support.
"""

# 2.5 mm wall, fully solid, is the design intent. Perimeter count therefore follows the
# nozzle: 4 x 0.625 at 0.6, 6 x 0.42 at 0.4.
_WALL_MM = 2.5

COMMON = {
    "top_shell_layers": "5",
    "bottom_shell_layers": "4",
    "sparse_infill_density": "20%",
    "sparse_infill_pattern": "gyroid",
    # The bores are modelled +0.4 mm on diameter for FDM shrink already; the slicer must
    # not add its own on top. 3dp/README.md says so explicitly.
    "xy_hole_compensation": "0",
    "xy_contour_compensation": "0",
    # Both shells print opening-down, which leaves the inside of the dome as a near-flat
    # ceiling ~100 x 80 mm. Not bridgeable. The shell is open to the plate, so the support
    # stands on the plate and lifts straight out.
    "enable_support": "1",
    "support_type": "normal(auto)",
    "support_on_build_plate_only": "1",
    "support_threshold_angle": "45",
    "support_top_z_distance": "0.2",
    "support_bottom_z_distance": "0.2",
    "support_base_pattern_spacing": "3",
    "brim_type": "outer_only",
    "brim_width": "5",
    "curr_bed_type": "Textured PEI Plate",
    "seam_position": "aligned",
}


def _walls(line_w):
    n = max(2, round(_WALL_MM / line_w))
    return {"wall_loops": str(n),
            "outer_wall_line_width": f"{line_w:.2f}",
            "inner_wall_line_width": f"{line_w:.2f}"}


VARIANTS = {
    "absgf-0.4": dict(
        machine="Bambu Lab H2C 0.4 nozzle",
        process="0.24mm Standard @BBL H2C",
        filament="Bambu ABS-GF @BBL H2C 0.4 nozzle",
        nozzle="0.4", filament_id="GFB50", filament_type="ABS-GF",
        process_name="0.24mm CANary Case ABS-GF @BBL H2C 0.4",
        note="structural part: glass-filled ABS, enclosed chamber, hardened nozzle",
        overrides={**COMMON, **_walls(0.42),
                   # ABS-GF shrinks; a 137 x 87 footprint wants all the bed it can get.
                   "brim_width": "8"},
    ),
    "pla-0.4": dict(
        machine="Bambu Lab H2C 0.4 nozzle",
        process="0.24mm Standard @BBL H2C",
        filament="Bambu PLA Basic @BBL H2C",
        nozzle="0.4", filament_id="GFA00", filament_type="PLA",
        process_name="0.24mm CANary Case PLA @BBL H2C 0.4",
        note="fit-check article only -- PLA creeps under the panel-screw preload",
        overrides={**COMMON, **_walls(0.42)},
    ),
    "pla-0.4-flat": dict(
        geometry="flat",
        machine="Bambu Lab H2C 0.4 nozzle",
        process="0.24mm Standard @BBL H2C",
        filament="Bambu PLA Basic @BBL H2C",
        nozzle="0.4", filament_id="GFA00", filament_type="PLA",
        process_name="0.24mm CANary LED insert PLA @BBL H2C 0.4",
        note="the LED window insert for the flat case: natural or white PLA, tile down",
        overrides={**COMMON, **_walls(0.42),
                   "enable_support": "0",
                   # four 4 x 3 mm pillars 30 mm tall: give each layer time to set
                   "slow_down_for_layer_cooling": "1",
                   "slow_down_min_speed": "10",
                   "slow_down_layer_time": "8"},
    ),
    "pla-0.4-tube": dict(
        geometry="tube",
        machine="Bambu Lab H2C 0.4 nozzle",
        process="0.24mm Standard @BBL H2C",
        filament="Bambu PLA Basic @BBL H2C",
        nozzle="0.4", filament_id="GFA00", filament_type="PLA",
        process_name="0.24mm CANary LED insert PLA tube @BBL H2C 0.4",
        filament_colour="#FFFFFF",
        note="the white PLA parts for the one-piece tube: LED window insert and switch "
             "cover. The tube's window sits 1.5 mm left and its pillars are 1.6 mm "
             "shorter than the flat case's, so the inserts do not swap; since the tube "
             "took a flush pocket for its cover, the tube's cover fits only the tube",
        overrides={**COMMON, **_walls(0.42),
                   "enable_support": "0",
                   "slow_down_for_layer_cooling": "1",
                   "slow_down_min_speed": "10",
                   "slow_down_layer_time": "8"},
    ),
    "pla-0.4-jig": dict(
        geometry="jig",
        machine="Bambu Lab H2C 0.4 nozzle",
        process="0.24mm Standard @BBL H2C",
        filament="Bambu PLA Basic @BBL H2C",
        nozzle="0.4", filament_id="GFA00", filament_type="PLA",
        process_name="0.24mm CANary insert jig PLA @BBL H2C 0.4",
        note="the heat-set insert jig (gen_insert_jig.py): index plate, nest and peg. "
             "Workshop tooling, never near the iron's heat, so plain PLA",
        overrides={**COMMON,
                   "wall_loops": "3",
                   "sparse_infill_density": "15%",
                   "enable_support": "0"},
    ),
    "absgf-0.4-dualsupport": dict(
        machine="Bambu Lab H2C 0.4 nozzle",
        process="0.24mm Standard @BBL H2C",
        filament="Bambu ABS-GF @BBL H2C 0.4 nozzle",
        nozzle="0.4", filament_id="GFB50", filament_type="ABS-GF",
        # The H2C has two nozzles. Filament 2 is Bambu Support for ABS, which is what
        # makes the zero gap below legal: it is formulated not to weld to ABS, so the
        # interface can sit hard against the model and still lift off. Same-material
        # support cannot do that at any gap -- 0.2 mm of ABS-GF onto ABS-GF is a weld.
        support_filament="Bambu Support for ABS @BBL H2C 0.4 nozzle",
        support_filament_id="GFS06", support_filament_type="ABS",
        process_name="0.24mm CANary Case ABS-GF dual @BBL H2C 0.4",
        note="the one to print: ABS-GF body, Support for ABS on the second nozzle",
        overrides={**COMMON, **_walls(0.42),
                   "brim_width": "8",
                   # 1-indexed filament numbers, so 2 == the support spool.
                   "support_filament": "2",
                   "support_interface_filament": "2",
                   # Bambu's own figure for this material: 0 top Z distance and 0
                   # interface spacing give a scar-free downward face. Base pattern
                   # spacing is deliberately left at COMMON's 3 so the material figures
                   # stay comparable with absgf-0.4.
                   "support_top_z_distance": "0",
                   "support_bottom_z_distance": "0",
                   "support_interface_spacing": "0"},
    ),
    "absgf-0.4-flat": dict(
        geometry="flat",
        machine="Bambu Lab H2C 0.4 nozzle",
        process="0.24mm Standard @BBL H2C",
        filament="Bambu ABS-GF @BBL H2C 0.4 nozzle",
        nozzle="0.4", filament_id="GFB50", filament_type="ABS-GF",
        process_name="0.24mm CANary Case ABS-GF flat @BBL H2C 0.4",
        note="flat-section case: shells print outer face down, no support, one nozzle",
        overrides={**COMMON, **_walls(0.42),
                   "brim_width": "8",
                   # Nothing on this geometry overhangs past 45 deg from the plate up:
                   # the domes are gone, the ledges are open, the rails and tubes stand
                   # on the lid. The slicer is told so rather than left to find bridges.
                   "enable_support": "0",
                   # Keep detection on so a regression in the geometry shows up in the
                   # slice preview as blue overhang walls, not as a failed print.
                   "detect_overhang_wall": "1"},
    ),
    "absgf-0.4-tube": dict(
        geometry="tube",
        machine="Bambu Lab H2C 0.4 nozzle",
        process="0.24mm Standard @BBL H2C",
        filament="Bambu ABS-GF @BBL H2C 0.4 nozzle",
        nozzle="0.4", filament_id="GFB50", filament_type="ABS-GF",
        process_name="0.24mm CANary Case ABS-GF tube @BBL H2C 0.4",
        note="one-piece body standing on its rear end + two end plates; no support",
        overrides={**COMMON, **_walls(0.42),
                   "brim_width": "8",
                   # Standing up, every layer of the body is the section's own ring.
                   # The guide tubes are teardrops on fins; the window and slot edges
                   # are 10-13 mm bridges. No support, and bridges are left to bridge.
                   "enable_support": "0",
                   "bridge_no_support": "1",
                   "detect_overhang_wall": "1"},
    ),
    "absgf-0.4-tube-x4": dict(
        geometry="tube",
        machine="Bambu Lab H2C 0.4 nozzle",
        process="0.24mm Standard @BBL H2C",
        filament="Bambu ABS-GF @BBL H2C 0.4 nozzle",
        nozzle="0.4", filament_id="GFB50", filament_type="ABS-GF",
        process_name="0.24mm CANary Case ABS-GF tube x4 @BBL H2C 0.4",
        note="a production plate: four bodies and their eight end plates on one bed; "
             "the brim drops to 3 mm because twelve 137 x 45 footprints do not fit "
             "the 350 x 320 bed with 8 mm around each",
        overrides={**COMMON, **_walls(0.42),
                   "brim_width": "3",
                   "enable_support": "0",
                   "bridge_no_support": "1",
                   "detect_overhang_wall": "1"},
    ),
    "asa-0.6": dict(
        machine="Bambu Lab H2C 0.6 nozzle",
        process="0.30mm Standard @BBL H2C 0.6 nozzle",
        filament="Bambu ASA @BBL H2C 0.6 nozzle",
        nozzle="0.6", filament_id="GFB98", filament_type="ASA",
        process_name="0.30mm CANary Case @BBL H2C 0.6",
        note="the design spec in 3dp/README.md; needs a 0.6 nozzle and ASA",
        overrides={**COMMON, **_walls(0.625)},
    ),
}

DEFAULT = "absgf-0.4-dualsupport"
