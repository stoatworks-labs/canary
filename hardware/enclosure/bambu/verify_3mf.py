#!/usr/bin/env python3
"""Gate a built 3mf before it ships.

The CLI slicing a file is NOT proof the GUI can open it: a hand-assembled
project_settings.config carries preset-system leftovers that the slicer ignores and Studio
rejects on load. This checks the things that actually broke:

  * every build item resolves to an object that carries triangles
  * no preset-only directive survived into the project config
  * the filament and machine identity is internally consistent
  * the machine G-code is the printer's own, not the stock placeholder a preset
    flattened without its `include` templates falls back to
  * on a multi-filament plate, project, plate and sliced G-code all agree on which
    nozzle prints which filament

Usage: verify_3mf.py <file.3mf>   (exit 1 on failure)
"""
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {'m': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}

# Keys that belong to Bambu's PRESET system and must never reach a project config.
# Checked against what Studio itself writes: a real project keeps `from` (= "project")
# and `name` (= "project_settings") and carries none of these.
PRESET_ONLY = ('include', 'inherits', 'instantiation', 'setting_id', 'type',
               'compatible_printers_condition', 'compatible_prints_condition')

# fdm_machine_common's machine_start_gcode: what every Bambu machine preset inherits and
# then replaces through its `include` templates. If a project still carries it, the
# templates were never applied -- no chamber heat, no bed levelling, a 205 C purge line
# at x 10 -- and the slicer will not say a word.
STOCK_START_GCODE = 'G0 Z20 F9000\nG92 E0; G1 E-10 F1200\nG28\nM970'


def fail(msg, errs):
    errs.append(msg)


def main(path):
    errs = []
    z = zipfile.ZipFile(path)
    names = z.namelist()

    # ---- geometry ---------------------------------------------------------
    model = ET.fromstring(z.read('3D/3dmodel.model'))
    build = model.find('m:build', NS)
    res = model.find('m:resources', NS)
    items = build.findall('m:item', NS) if build is not None else []
    objs = {o.get('id'): o for o in (res.findall('m:object', NS) if res is not None else [])}
    if not items:
        fail("no build items -- the plate is empty", errs)

    # triangles, wherever they live (inline, or in an external object part)
    tri_by_part = {}
    for n in names:
        if n.startswith('3D/Objects/') and n.endswith('.model'):
            sub = ET.fromstring(z.read(n))
            t = 0
            for so in sub.iter('{%s}triangles' % NS['m']):
                t += len(so)
            tri_by_part[n] = t
    inline = 0
    for o in objs.values():
        for t in o.iter('{%s}triangles' % NS['m']):
            inline += len(t)
    total_tris = inline + sum(tri_by_part.values())

    for it in items:
        if it.get('objectid') not in objs:
            fail(f"build item objectid={it.get('objectid')} resolves to nothing", errs)
    for n, t in sorted(tri_by_part.items()):
        if t == 0:
            fail(f"{n} carries no triangles", errs)
    if total_tris == 0:
        fail("the file contains no geometry at all", errs)

    # ---- project config ---------------------------------------------------
    try:
        cfg = json.loads(z.read('Metadata/project_settings.config'))
    except KeyError:
        cfg = None
        fail("no Metadata/project_settings.config", errs)

    if cfg is not None:
        for k in PRESET_ONLY:
            if k in cfg:
                fail(f"preset-only key {k!r} = {cfg[k]!r} leaked into the project "
                     f"config -- the GUI errors on this even though the CLI slices it",
                     errs)
        if cfg.get('from') not in (None, 'project'):
            fail(f"from={cfg['from']!r}; a project config says 'project'", errs)
        nf = len(cfg.get('filament_settings_id', []))
        for k in ('filament_ids', 'filament_type', 'filament_colour'):
            if k in cfg and isinstance(cfg[k], list) and len(cfg[k]) != nf:
                fail(f"{k} has {len(cfg[k])} entries for {nf} filament(s)", errs)
        # Per-variant filament arrays are indexed by filament_extruder_variant. If that
        # disagrees with the arrays it indexes, Studio answers "Invalid configuration
        # file" and the CLI says nothing at all.
        variants = cfg.get('filament_extruder_variant', [])
        if variants:
            for k in ('nozzle_temperature', 'filament_max_volumetric_speed',
                      'filament_flow_ratio', 'filament_retraction_length'):
                v = cfg.get(k)
                if isinstance(v, list) and len(v) != len(variants):
                    fail(f"{k} has {len(v)} entries but filament_extruder_variant "
                         f"declares {len(variants)}", errs)
        elif nf:
            fail("filament_extruder_variant is empty", errs)

        # Support routing. `support_filament` is 1-indexed into the filament list, 0
        # meaning "same as the model". Pointing it past the end is the failure that turns
        # a dual-material plate back into a single-material one without saying so.
        for k in ('support_filament', 'support_interface_filament'):
            v = cfg.get(k)
            if v is None:
                continue
            try:
                i = int(v)
            except (TypeError, ValueError):
                fail(f"{k}={v!r} is not an integer", errs)
                continue
            if i < 0 or i > nf:
                fail(f"{k}={i} but the project has {nf} filament(s)", errs)
        if nf > 1:
            fmap = cfg.get('filament_map', [])
            if len(fmap) != nf:
                fail(f"filament_map has {len(fmap)} entries for {nf} filaments", errs)
            elif cfg.get('filament_map_mode') == 'Manual' and len(set(fmap)) < 2:
                fail(f"filament_map={fmap} puts every filament on one extruder; "
                     f"a dual-nozzle plate wants them split", errs)

            # The project-level map above is only a default. The slicer maps each PLATE
            # by its own filament_map_mode / filament_maps in model_settings.config,
            # and the CLI export leaves those at "Auto For Flush" -- which is how a
            # plate shipped saying 1,2 with G-code sliced 2,1 inside it. All three
            # must agree: project, every plate, and the header of any G-code carried.
            want = ' '.join(str(x) for x in fmap)
            try:
                ms = z.read('Metadata/model_settings.config').decode()
            except KeyError:
                ms = ''
                fail("no Metadata/model_settings.config", errs)
            plates = re.findall(r'<plate>(.*?)</plate>', ms, flags=re.S)
            if not plates:
                fail("model_settings.config has no <plate> block", errs)
            for i, p in enumerate(plates, 1):
                mode = re.search(r'key="filament_map_mode" value="([^"]*)"', p)
                maps = re.search(r'key="filament_maps" value="([^"]*)"', p)
                mode = mode.group(1) if mode else None
                maps = maps.group(1) if maps else None
                if mode != 'Manual':
                    fail(f"plate {i} filament_map_mode={mode!r}; the slicer decides "
                         f"the nozzles itself unless this says Manual", errs)
                if maps != want:
                    fail(f"plate {i} filament_maps={maps!r} but the project's "
                         f"filament_map is {want!r}", errs)
            for n in names:
                if not re.fullmatch(r'Metadata/plate_\d+\.gcode', n):
                    continue
                head = z.read(n)[:4 * 1024 * 1024].decode('utf-8', 'replace')
                got = re.search(r'^; filament_map = (.*)$', head, flags=re.M)
                got = got.group(1).strip().replace(',', ' ') if got else None
                if got != want:
                    fail(f"{n} was sliced with filament_map {got!r}, not the "
                         f"project's {want!r} -- the file disagrees with itself",
                         errs)

        # The machine G-code. Bambu keeps the real start/end/change blocks in
        # "<machine> template <key>.json" files that the machine preset `include`s;
        # a flatten that only follows `inherits` gets fdm_machine_common's placeholder
        # instead, and the CLI slices that just as happily.
        start = cfg.get('machine_start_gcode', '')
        if start.startswith(STOCK_START_GCODE):
            fail("machine_start_gcode is fdm_machine_common's stock placeholder -- the "
                 "machine preset's `include` templates were not resolved", errs)
        chamber = [float(t) for t in cfg.get('chamber_temperatures', [])
                   if str(t).replace('.', '', 1).isdigit()]
        if chamber and max(chamber) >= 40 and not re.search(r'M1[49]1\b', start):
            fail(f"chamber_temperatures={cfg.get('chamber_temperatures')} but the "
                 f"start G-code never heats the chamber (no M141/M191)", errs)

        nozzles = cfg.get('nozzle_diameter', [])
        if nozzles and len(set(nozzles)) != 1:
            fail(f"mixed nozzle_diameter {nozzles}", errs)
        if cfg.get('printer_variant') and nozzles and \
                str(cfg['printer_variant']) != str(nozzles[0]):
            fail(f"printer_variant {cfg['printer_variant']} != nozzle "
                 f"{nozzles[0]}", errs)
        for k in ('print_compatible_printers',):
            v = cfg.get(k)
            if v and cfg.get('printer_settings_id') not in v:
                fail(f"{k}={v} does not list printer_settings_id "
                     f"{cfg.get('printer_settings_id')!r}", errs)

    label = (f"{len(items)} object(s), {total_tris} triangles"
             if cfg is None else
             f"{len(items)} object(s), {total_tris} triangles, "
             f"{cfg.get('filament_type')} on {cfg.get('printer_settings_id')} "
             f"@ {cfg.get('layer_height')} mm")
    if errs:
        print(f"VERIFY FAILED  {path}")
        for e in errs:
            print(f"  ! {e}")
        return 1
    print(f"  verified {path}: {label}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
