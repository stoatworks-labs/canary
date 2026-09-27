"""Build Metadata/project_settings.config for whichever variant flatten_preset.py last ran.

The CLI cannot invent an H2C's dual-nozzle plumbing: a project it builds from scratch comes
out with empty `extruder_nozzle_stats` and slices with "No valid nozzle found". So this
grounds the config in a real Studio-made H2C project and overlays our own process and
filament keys onto it.

The reference is a 0.4 nozzle PLA project, so the machine- and filament-identifying keys are
rewritten too. `print_compatible_printers` is the one that bites: leave the reference's value
in place and the slicer answers `run 3002: process not compatible with printer`, however
correct everything else is.

The reference project is not in the repo. Point CANARY_H2C_REF_3MF at any 3MF you have
sliced for an H2C in Bambu Studio itself (0.4 nozzle, PLA is what this was built against):

    CANARY_H2C_REF_3MF=~/some-h2c-project.3mf ./build.sh
"""
import json
import os
import sys
import zipfile

REF = os.environ.get('CANARY_H2C_REF_3MF', '')
if not REF:
    sys.exit("make_project_config.py: set CANARY_H2C_REF_3MF to a Bambu Studio-made H2C "
             "project (.3mf) to ground the config in -- see this file's docstring")
REF = os.path.expanduser(REF)
if not os.path.isfile(REF):
    sys.exit(f"make_project_config.py: CANARY_H2C_REF_3MF={REF!r} is not a file")
SKIP = ('type', 'from', 'instantiation', 'name', 'compatible_printers',
        'compatible_printers_condition', 'description', 'setting_id', 'inherits',
        'compatible_prints', 'compatible_prints_condition',
        # `include` is a directive to Bambu's PRESET system ("pull in
        # fdm_filament_template_direct_dual_e3d"), not a setting. Copied into a project
        # config it is an instruction to resolve a template that is not there, and
        # Studio's own re-export drops it. Leave it in and the GUI errors on load even
        # though the CLI slices the file quite happily.
        'include')

paths = json.load(open('presets/paths.json'))
MACHINE, NOZZLE = paths['machine_name'], paths['nozzle']

with zipfile.ZipFile(REF) as z:
    cfg = json.loads(z.read('Metadata/project_settings.config'))
assert cfg['extruder_nozzle_stats'], "reference lost its nozzle stats"

proc = json.load(open(paths['process']))
fila = json.load(open(paths['filament']))
mach = json.load(open(paths['machine']))


def identity(cfg):
    """Machine- and process-identifying keys, applied the same way in both modes."""
    cfg['printer_settings_id'] = MACHINE
    cfg['print_settings_id'] = proc['name']
    cfg['printer_variant'] = NOZZLE
    cfg['nozzle_diameter'] = [NOZZLE] * len(cfg['nozzle_diameter'])
    for k in ('printer_model', 'printable_height', 'printable_area'):
        if k in mach:
            cfg[k] = mach[k]
    cfg['print_compatible_printers'] = [MACHINE]
    cfg['upward_compatible_machine'] = mach.get('upward_compatible_machine', [])
    cfg['different_settings_to_system'] = [''] * len(
        cfg.get('different_settings_to_system', ['']))


if paths.get('support_filament'):
    # ---- dual-material -------------------------------------------------------------
    #
    # The single-filament path below overlays onto a Studio-made reference and forbids
    # any array from changing length. A second filament changes 143 of them, so that
    # invariant cannot hold and there is no honest way to fake the new shapes: the
    # filament_* arrays are a flat list of (filament, extruder-variant) pairs, indexed by
    # `filament_self_index` and named by `filament_extruder_variant`. The reference is
    # 1 filament x 3 variants; we need 2 filaments x 1 variant, which is a different
    # layout, not a longer one.
    #
    # So take the shapes from the CLI's own export of THIS plate -- Studio resolved them
    # itself, for exactly these two presets -- and graft back only what the CLI leaves
    # empty. That is two keys. Both are the H2C's nozzle plumbing, and the empty
    # `extruder_nozzle_stats` is precisely the "No valid nozzle found" this file exists
    # to work around.
    raw = sys.argv[1] if len(sys.argv) > 1 else None
    if not raw:
        raise SystemExit("dual-material variant needs the raw CLI export: "
                         "make_project_config.py <raw.3mf>")
    with zipfile.ZipFile(raw) as z:
        cfg = json.loads(z.read('Metadata/project_settings.config'))

    # The CLI export is built from PRESETS, so it arrives carrying preset-system keys that
    # a Studio-made project does not have -- the single-filament path never sees them
    # because it starts from a real project and copies in through SKIP. Same list as
    # verify_3mf.py's PRESET_ONLY, which is what fails the build if one survives.
    for k in ('include', 'inherits', 'instantiation', 'setting_id', 'type',
              'compatible_printers_condition', 'compatible_prints_condition'):
        cfg.pop(k, None)

    GRAFT = ('extruder_nozzle_stats', 'extruder_ams_count', 'extruder_nozzle_stats_new')
    with zipfile.ZipFile(REF) as z:
        refcfg = json.loads(z.read('Metadata/project_settings.config'))
    for k in GRAFT:
        if refcfg.get(k):
            cfg[k] = refcfg[k]
    assert cfg['extruder_nozzle_stats'], "graft failed: still no nozzle stats"

    # The CLI export is a plate, not a process: it carries the stock process settings.
    n = 0
    for k, v in proc.items():
        if k in SKIP:
            continue
        cfg[k] = v
        n += 1

    # Both filaments came in through --load-filaments, so the arrays are already right;
    # assert that rather than rewrite them.
    want = [paths['filament_type'], paths['support_filament_type']]
    assert cfg['filament_type'] == want, f"filament_type is {cfg['filament_type']}, want {want}"
    assert cfg['filament_ids'] == [paths['filament_id'], paths['support_filament_id']], \
        f"filament_ids is {cfg['filament_ids']}"

    # Put the two filaments on the two nozzles explicitly. Left to "Auto For Flush" the
    # slicer is free to land both on the AMS extruder, which reintroduces a wipe tower and
    # a per-swap purge -- the exact cost this variant exists to avoid. ABS-GF is the one
    # that wants the AMS (extruder 2, `extruder_max_nozzle_count` 6); the support spool
    # sits on the single-spool nozzle (extruder 1).
    # Flush arrays are COMPUTED, not grafted and not left as the CLI wrote them.
    #
    # The slicer wants exactly `extruders * filaments**2` entries in the matrix and
    # `extruders * filaments` in the vector -- measured by sweeping sizes until one
    # sliced: 8 and 4 here, for 2 filaments on 2 nozzles. Anything else is
    # "Flush volumes matrix do not match to the correct size!".
    #
    # Neither the reference nor the CLI export can supply that. The reference is a
    # 1-filament project carrying 50 and 10, which survives only because a plate with
    # nothing to flush never runs the check; the CLI writes 16 and 8, sized for four
    # slots. Both are wrong the moment a second filament exists.
    #
    # Values follow Bambu's own arithmetic -- flushing A into B costs vector[A]+vector[B],
    # and nothing at all on the diagonal. They are inert either way while `filament_map`
    # keeps the two filaments on separate nozzles: no shared nozzle, no purge.
    n_ext = len(cfg['nozzle_diameter'])
    n_fil = len(cfg['filament_settings_id'])
    unit = 140
    vec = [str(unit)] * (n_ext * n_fil)
    cfg['flush_volumes_vector'] = vec
    cfg['flush_volumes_matrix'] = [
        '0' if i == j else str(unit * 2)
        for _ in range(n_ext) for i in range(n_fil) for j in range(n_fil)]
    cfg['flush_multiplier'] = ['1'] * n_ext
    cfg['flush_multiplier_fast'] = ['1'] * n_ext

    # Put the two filaments on the two nozzles explicitly. Left to "Auto For Flush" the
    # slicer is free to land both on one extruder, which reintroduces a wipe tower and a
    # per-swap purge -- the exact cost this variant exists to avoid.
    #
    # ABS-GF on extruder 2, support on extruder 1. Extruder 2 is the right-hand nozzle,
    # physical T0, the one the AMS feeds (`extruder_ams_count`); extruder 1 is the
    # left-hand nozzle, T1, the external spool. So the body comes out of the AMS and the
    # support spool hangs on the side, which is how the printer is loaded anyway.
    #
    # (This used to be ['1', '2'], on the grounds that the machine start G-code lays a
    # purge line at x 10 which only extruder 1 reaches. That purge line belonged to
    # fdm_machine_common's generic start G-code, which is what a preset flattened
    # without its `include` templates falls back to; the H2C's real start block has no
    # such line and either map slices. See flatten_preset.py.)
    #
    # Note this key is only the project-level default. The slicer takes the map from the
    # PLATE -- `filament_map_mode` / `filament_maps` in model_settings.config -- which the
    # CLI export leaves at "Auto For Flush". inject_config.py copies these two keys onto
    # every plate, and verify_3mf.py fails the build if the two ever disagree.
    cfg['filament_map_mode'] = 'Manual'
    cfg['filament_map'] = ['2', '1']

    # The prime tower defaults to x 15, which is inside extruder 2's dead strip. Both
    # nozzles print the tower, so it has to sit in x >= 25 like everything else.
    #
    # It is kept rather than switched off. Nothing is ever purged BETWEEN materials here
    # -- each nozzle holds one filament for the whole print -- but `filament_prime_volume`
    # is 30 mm3 per resume, and with support on nearly every one of the 256 layers the
    # model nozzle restarts constantly. Without a tower that prime has nowhere to go and
    # the first extrusion of each layer runs thin. It costs 10.5 g of the plate; set
    # enable_prime_tower to 0 in the variant overrides to trade that back.
    #
    # (30, 10) is clear space measured off the sliced plate: the parts occupy
    # x 38..309, y 46..274, and the tower is 28.5 x 26.6 mm.
    cfg['wipe_tower_x'] = ['30']
    cfg['wipe_tower_y'] = ['10']

    # --load-filaments leaves this at one entry however many filaments it loaded, and
    # verify_3mf.py checks it against the filament count. Support for ABS only ships
    # white, so the preview reads as body vs support at a glance.
    cfg['filament_colour'] = ['#161616', '#FFFFFF']
    if isinstance(cfg.get('filament_multi_colour'), list):
        cfg['filament_multi_colour'] = ['#161616', '#FFFFFF']

    identity(cfg)
    json.dump(cfg, open('project_settings.json', 'w'), indent=4)
    print(f"[{paths['variant']}] dual-material: overlaid {n} process keys onto the CLI "
          f"export, grafted {len(GRAFT)} nozzle keys from the reference "
          f"({len(cfg)} keys)")
    for k in ['printer_settings_id', 'print_settings_id', 'filament_settings_id',
              'filament_type', 'filament_ids', 'filament_map', 'filament_map_mode',
              'filament_self_index', 'filament_extruder_variant', 'nozzle_diameter',
              'support_filament', 'support_interface_filament', 'support_top_z_distance',
              'support_interface_spacing', 'enable_support', 'layer_height', 'wall_loops',
              'nozzle_temperature', 'extruder_nozzle_stats', 'curr_bed_type']:
        print(f"  {k} = {cfg.get(k)}")
    raise SystemExit(0)


n = 0
for k, v in proc.items():
    if k in SKIP:
        continue
    cfg[k] = v
    n += 1

# Filament settings are ARRAYS in a project config, and their length is NOT the filament
# count. The H2C keeps three extruder variants per filament -- `filament_extruder_variant`
# names them ("Direct Drive Standard", "... High Flow", "... E3D High Flow") -- so a
# single-filament project still carries 3-entry arrays for every per-variant setting.
#
# Assigning a preset's own value straight in collapses those to the preset's leaf length,
# usually 1. The result is a config where some filament_* arrays are 3 long and others 1,
# `filament_extruder_variant` disagrees with both, and Studio rejects the whole file with
# "Invalid configuration file" while the CLI slices it without complaint.
#
# So: the PROJECT decides the length, the PRESET decides the values.
FILAMENT_KEEP = (
    'filament_settings_id',
    # machine-defined, not filament-defined: it names the variants the arrays index
    'filament_extruder_variant',
)


def fit(value, length):
    """Expand a preset value to exactly `length` entries, never changing the length."""
    if not isinstance(value, list):
        return [value] * length
    if len(value) == length:
        return list(value)
    if len(value) == 1:
        return value * length
    if len(value) > length:
        return list(value[:length])
    return list(value) + [value[-1]] * (length - len(value))


shapes = {k: len(v) for k, v in cfg.items() if isinstance(v, list)}
f = 0
for k, v in fila.items():
    if k in SKIP or k in FILAMENT_KEEP:
        continue
    if k in cfg and isinstance(cfg[k], list):
        cfg[k] = fit(v, len(cfg[k]))
    elif k in cfg:
        cfg[k] = v[0] if isinstance(v, list) and v else v
    else:
        cfg[k] = v
    f += 1
cfg['filament_settings_id'] = [fila['name']]
cfg['filament_type'] = [paths['filament_type']]
cfg['filament_ids'] = [paths['filament_id']]
# Studio's AMS mapping matches the project colour to a loaded spool, so a part meant for
# a particular spool (the white LED inserts) says so here rather than in the preview's
# default black.
if paths.get('filament_colour'):
    cfg['filament_colour'] = [paths['filament_colour']]
    if isinstance(cfg.get('filament_multi_colour'), list):
        cfg['filament_multi_colour'] = [paths['filament_colour']]

# Machine identity: the reference is a 0.4 PLA project.
identity(cfg)

# Nothing above is allowed to have reshaped the reference. This is the invariant that
# "Invalid configuration file" was really about, so fail loudly rather than ship it.
reshaped = [(k, shapes[k], len(cfg[k]))
            for k in shapes
            if isinstance(cfg.get(k), list) and len(cfg[k]) != shapes[k]
            and k not in ('filament_ids', 'filament_type', 'filament_settings_id',
                          'filament_colour')]
if reshaped:
    for k, was, now in reshaped:
        print(f"  ! {k}: {was} -> {now}")
    raise SystemExit("the overlay changed array lengths the project defines; "
                     "Studio will reject this as an invalid configuration file")

json.dump(cfg, open('project_settings.json', 'w'), indent=4)
print(f"[{paths['variant']}] overlaid {n} process + {f} filament keys "
      f"onto the reference ({len(cfg)} keys)")
for k in ['printer_settings_id', 'print_settings_id', 'filament_settings_id',
          'filament_type', 'filament_ids', 'nozzle_diameter', 'printer_variant',
          'layer_height', 'wall_loops', 'enable_support', 'brim_type',
          'xy_hole_compensation', 'nozzle_temperature', 'hot_plate_temp',
          'extruder_nozzle_stats', 'filament_map', 'curr_bed_type']:
    print(f"  {k} = {cfg.get(k)}")
