"""Flatten Bambu system presets (resolving `inherits`, which the CLI does not) so the
BambuStudio CLI can build the CANary case project.

    python3 flatten_preset.py [variant]      # see variants.py

Writes presets/<name>.json for machine, process and filament, plus presets/paths.json
which make_project_config.py and build.sh both read back.
"""
import json
import os
import sys

from variants import VARIANTS, DEFAULT

SYS = os.path.expanduser('~/Library/Application Support/BambuStudio/system/BBL')


# A preset is composed two ways, and the CLI resolves neither. `inherits` is the chain
# everyone knows about. `include` is the other half: since 02.0x the long machine G-code
# blocks (start, end, filament change, layer change, timelapse, wrapping detection) live in
# sibling "<machine> template <key>.json" files that the machine preset only NAMES here,
# and every H2C filament pulls its three-extruder-variant arrays in from
# fdm_filament_template_direct_dual_e3d the same way.
#
# Walk `inherits` alone and the machine chain bottoms out in fdm_machine_common's generic
# start G-code -- a 205 C purge line at x 10 and no chamber heat, on an ABS plate. That is
# what the first absgf-0.4-dualsupport plate shipped with, and nothing in the slice said
# so. Order is ancestors, then includes, then the preset's own keys: the ABS-GF leaf
# overrides five of the filament template's keys, and the template's 3-entry arrays have
# to beat the single-extruder ancestors'.
_META = ('name', 'instantiation', 'inherits', 'include')


def resolve(kind, name):
    p = os.path.join(SYS, kind, name + '.json')
    if not os.path.exists(p):
        raise SystemExit(f"missing preset: {p}")
    d = json.load(open(p))
    base = resolve(kind, d['inherits']) if d.get('inherits') else {}
    for inc in d.get('include', []):
        t = resolve(kind, inc)
        base.update({k: v for k, v in t.items() if k not in _META})
    base.update(d)
    return base


def flatten(kind, src, machine_name, overrides=None):
    m = resolve(kind, src)
    m.pop('inherits', None)
    m.pop('include', None)
    m['from'] = 'system'
    m['instantiation'] = 'true'
    if overrides:
        m.update(overrides)
    idkey = {'machine': 'printer_settings_id', 'process': 'print_settings_id',
             'filament': 'filament_settings_id'}[kind]
    m[idkey] = m['name']
    if kind != 'machine':
        m['compatible_printers'] = [machine_name]
        m['compatible_printers_condition'] = ''
    if kind == 'filament':
        m['compatible_prints'] = []
        m['compatible_prints_condition'] = ''
    out = f"presets/{m['name']}.json"
    json.dump(m, open(out, 'w'), indent=1)
    print(f"  {out}  ({len(m)} keys)")
    return m, out


def _bbox(area):
    """['0x0','330x0','330x320','0x320'] (or one comma-joined string) -> (x0,y0,x1,y1)."""
    pts = []
    for item in ([area] if isinstance(area, str) else area):
        for pt in str(item).split(','):
            x, _, y = pt.partition('x')
            pts.append((float(x), float(y)))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def write_arrange_machine(mach, out='presets/arrange-machine.json'):
    """A copy of the machine whose bed is only what BOTH nozzles can reach.

    The H2C's two extruders do not cover the same bed: `extruder_printable_area` gives
    extruder 1 x 0..325 and extruder 2 x 25..330. `--arrange` knows only `printable_area`,
    the union, so on a four-part plate it lays parts out from x 10 to x 308 -- and then the
    slicer refuses the result with "Found G-code in unprintable area of multi-extruder
    printers", because the ABS-GF is on extruder 2 and 15 mm of it is out of that nozzle's
    reach. Both filaments dip below x 25, so re-mapping them does not help; the layout has
    to change.

    This is used ONLY for the arrange/export pass, to place the objects. The project config
    that ships still carries the machine's real printable_area -- what is being constrained
    is where the parts sit, not what the printer is.
    """
    x0, y0, x1, y1 = _bbox(mach['printable_area'])
    for area in mach.get('extruder_printable_area', []):
        ex0, ey0, ex1, ey1 = _bbox(area)
        x0, y0 = max(x0, ex0), max(y0, ey0)
        x1, y1 = min(x1, ex1), min(y1, ey1)
    area = [f'{x0:g}x{y0:g}', f'{x1:g}x{y0:g}', f'{x1:g}x{y1:g}', f'{x0:g}x{y1:g}']
    arr = dict(mach)
    arr['printable_area'] = area
    # printable_height is the per-extruder minimum for the same reason.
    heights = [float(h) for h in mach.get('extruder_printable_height', [])]
    if heights:
        arr['printable_height'] = str(min(heights + [float(mach['printable_height'])]))
    json.dump(arr, open(out, 'w'), indent=1)
    print(f"  {out}  (arrange bed {x1 - x0:g} x {y1 - y0:g} at {x0:g},{y0:g} "
          f"-- both nozzles reach this)")
    return out


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if name not in VARIANTS:
        raise SystemExit(f"unknown variant {name!r}; have: {', '.join(VARIANTS)}")
    v = VARIANTS[name]
    print(f"variant {name} -- {v['note']}")
    os.makedirs('presets', exist_ok=True)

    mach, MP = flatten('machine', v['machine'], v['machine'],
                       {'nozzle_volume_type': ['Standard', 'Standard']})
    proc, PP = flatten('process', v['process'], v['machine'],
                       {**v['overrides'], 'name': v['process_name']})
    fila, FP = flatten('filament', v['filament'], v['machine'])

    paths = {'variant': name, 'machine': MP, 'process': PP, 'filament': FP,
             'machine_name': v['machine'], 'nozzle': v['nozzle'],
             'filament_id': v['filament_id'], 'filament_type': v['filament_type'],
             # which case: 'lozenge' (print/) or 'flat' (print-flat/); build.sh reads it
             'geometry': v.get('geometry', 'lozenge'),
             'filament_colour': v.get('filament_colour', '')}

    # A dual-material variant carries a second filament. It is flattened exactly like the
    # first; what makes it the SUPPORT one is `support_filament`/`support_interface_filament`
    # in the process overrides, which are 1-indexed into this list.
    sup = None
    if v.get('support_filament'):
        sup, SP = flatten('filament', v['support_filament'], v['machine'])
        paths.update({'support_filament': SP,
                      'support_filament_id': v['support_filament_id'],
                      'support_filament_type': v['support_filament_type']})
        paths['arrange_machine'] = write_arrange_machine(mach)

    json.dump(paths, open('presets/paths.json', 'w'), indent=1)
    print(f"  machine  nozzle={mach.get('nozzle_diameter')} "
          f"variant={mach.get('printer_variant')} height={mach.get('printable_height')}")
    print(f"  process  layer={proc.get('layer_height')} "
          f"walls={proc.get('wall_loops')} x {proc.get('outer_wall_line_width')} "
          f"support={proc.get('enable_support')}")
    print(f"  filament {fila.get('filament_type')} id={fila.get('filament_id')} "
          f"nozzle={fila.get('nozzle_temperature')} bed={fila.get('hot_plate_temp')}")
    if sup:
        print(f"  support  {sup.get('filament_type')} id={sup.get('filament_id')} "
              f"nozzle={sup.get('nozzle_temperature')} "
              f"is_support={sup.get('filament_is_support')} "
              f"-> filament 2, support_filament="
              f"{proc.get('support_filament')} interface={proc.get('support_interface_filament')}")


if __name__ == '__main__':
    main()
