import json, re, zipfile, sys

src, dst, cfg = sys.argv[1], sys.argv[2], sys.argv[3]
with zipfile.ZipFile(src) as z:
    items = {k: z.read(k) for k in z.namelist()}
config = json.load(open(cfg))
items['Metadata/project_settings.config'] = json.dumps(config, indent=4).encode()

# The CLI names objects after their STL files; give Studio's object list real names.
NAMES = [
    ('canary_tube.stl', 'CANary case - body (one piece)'),
    ('canary_shell_bottom.stl', 'CANary case - shell bottom'),
    ('canary_shell_top.stl', 'CANary case - shell top'),
    ('canary_end_front.stl', 'CANary case - end front (3x etherCON)'),
    ('canary_end_rear.stl', 'CANary case - end rear (USB-C)'),
    ('canary_led_insert.stl', 'CANary case - LED window insert (PLA)'),
    ('canary_switch_cover.stl', 'CANary case - switch cover (PLA)'),
]
ms = items['Metadata/model_settings.config'].decode()
for old, new in NAMES:
    ms = ms.replace(f'value="{old}"', f'value="{new}"')

# Which nozzle prints which filament is decided PER PLATE, in this file, not by the
# `filament_map` in project_settings.config -- that one is only the project default.
# The CLI export writes every plate as "Auto For Flush", so the slicer chooses for itself
# and the project config goes on claiming whatever it was told. The first dual-support
# plate shipped that way: project_settings said Manual 1,2 and the G-code inside it was
# sliced 2,1. So stamp the project's map onto every plate here.
fmap = config.get('filament_map', [])
if len(fmap) > 1 and config.get('filament_map_mode') == 'Manual':
    maps = ' '.join(str(x) for x in fmap)

    def stamp(plate):
        body = re.sub(r'\s*<metadata key="filament_map(?:_mode|s)" value="[^"]*"/>', '',
                      plate.group(1))
        return (f'<plate>{body}\n    <metadata key="filament_map_mode" value="Manual"/>'
                f'\n    <metadata key="filament_maps" value="{maps}"/>\n  </plate>')

    ms, n = re.subn(r'<plate>(.*?)\s*</plate>', stamp, ms, flags=re.S)
    if not n:
        raise SystemExit("model_settings.config has no <plate> block to stamp the "
                         "filament map onto")
    print(f"stamped filament_maps=\"{maps}\" (Manual) onto {n} plate(s)")

items['Metadata/model_settings.config'] = ms.encode()

with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as z:
    for k, b in items.items():
        z.writestr(k, b)
print(f"wrote {dst}")
