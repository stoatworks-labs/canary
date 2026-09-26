# hardware/scripts

Every script here runs under **KiCad's bundled Python**, not the system one:

```
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
```

`render.sh` is the exception — it only shells out to `kicad-cli`.

> **Close KiCad first.** These write `dbcanary.kicad_pcb` directly. The GUI holds
> the board in memory and will happily overwrite whatever a script just did —
> that is how this board got corrupted once already.

## Pipeline, in order

Board geometry:

| # | Script | Does |
|---|---|---|
| 1 | `sync_pcb.py` | schematic → PCB. One pass **per process**: `--add`, then `--nets`, then `--verify` |
| 2 | `place.py` | board outline + component placement; solves the isolated-domain parts by search |
| 3 | `verify_place.py` | courtyard overlaps, pads outside outline, **isolation-domain membership** |
| 4 | `zones.py` | copper pours, isolation-barrier and plane-void rule areas |
| 5 | `verify_zones.py` | boolean-intersects the *poured* copper against the forbidden regions |
| 6 | `route_residual.py` | hand-routes the nets the autorouter cannot. **Run BEFORE freerouting** |
| 7 | *(freerouting)* | export DSN, retype `In1.Cu` to `power`, autoroute, import SES — see git log |
| 8 | `stitch2.py` | via-stitches the pour nets; correct per-layer + hole-to-hole model |
| 9 | `prune_vias.py` | deletes stitching vias DRC objects to (they are redundant by design) |
| 10 | `fix_clearance.py` | nudges autorouter vias that violate clearance, moving their tracks too |
| 11 | `fix_silkscreen.py` | shrinks refdes to 0.8 mm and nudges only those provably colliding |
| 12 | `route_usb_pair.py` | re-lays USB_DP/USB_DM as a coupled, length-matched pair. `--stitch`, `--verify`, `--dry-run` |

Outputs:

| # | Script | Does |
|---|---|---|
| 12 | `write_lcsc_fields.py` | writes LCSC / MPN / Manufacturer onto footprints as **hidden** fields |
| 13 | `run_vendor_toolkits.py` | drives the vendors' own Fabrication Toolkit plugins headlessly |
| 14 | `render.sh` | top / bottom / isometric renders into `docs/renders/` |

Part sourcing:

| Script | Does |
|---|---|
| `jlc_search.py` | finds LCSC parts via JLCPCB's own API, validated by component **type** and value |
| `jlc_verify.py` | re-queries every assigned code and requires an exact match, in stock |
| `jlc_rotations.py` | **cross-check only.** Compares rotations against kicad-jlcpcb-tools' database. The vendor toolkit applies corrections itself now, but this is what found the D201 conflict |

## Things that will bite you

**Paths are derived from `__file__`, not hardcoded.** Every script used to
carry an absolute `~/Projects/dbcanary/...` path, which stopped resolving when
the repo tree was reorganised — silently, because most of them then read a
board that was not there or wrote nothing. They now compute the repo root from
their own location. Keep it that way.

**`board.Add()` kills the Python proxy, and net objects go stale.** Placing vias
in a loop with `SetNet(<NETINFO_ITEM>)` put two of four on the wrong net, and
re-running moved *which* two. Setting the net *after* `Add()` fails the same way
on about one run in three. The rule that holds: build the item, `SetNetCode(int)`
on it, `Add()` last, and never touch the object again. Then re-read the saved
file in a fresh process to check — `route_usb_pair.py --verify` parses the
`.kicad_pcb` as text for exactly this reason, because `LoadBoard()` +
`GetNetname()` also returned wrong nets while the file on disk was correct.

**`board.Save()` re-nets a via that sits in a stale zone fill.** Add a via
inside a pour that was filled before it existed and the pour has no clearance
hole for it, so the connectivity rebuild inside `Save()` sees the barrel
touching that copper and reassigns the via to *that* net. It survives
`SetNetCode()`, survives `Add()`, and still reads correctly from
`board.GetTracks()` right up to the save — then the file says otherwise. It
picks a different subset each run, which makes it look like a zone-fill race.
Four GND vias dropped into the In2 `VCC_3V3` plane came out two-bad, clean,
clean, one-bad, clean over five identical runs. **Run `ZONE_FILLER` over the
zones in the same process, after the `Add()`s and before the `Save()`** — that
cuts the clearance hole first and made six consecutive runs come out right.
`route_usb_pair.py --stitch` does this.

**Zone fills are invisible to `route_residual.collect()`.** It reports pads and
tracks only. A via site can therefore look completely free while sitting inside
another net's plane with no copper of its own net anywhere near — and KiCad will
then absorb the via into that plane. If you are placing a via that must join a
pour, test the pour polygons directly, and leave a margin: a via carves a 1 mm
hole, so a site near a pour edge gets orphaned by the *next* refill.

**pcbnew's SWIG bindings degrade after mutation.** Once a script has called
`Remove()`, `Add()`, `FootprintLoad()` or `ZONE_FILLER`, later calls can return
untyped `SwigPyObject`s — even a fresh `LoadBoard()`. Two rules:

- **query first, mutate second** within a pass;
- **one pass per process** where that is not enough. `sync_pcb.py` takes
  `--add` / `--nets` / `--verify` for exactly this reason.

**`SetField()` creates fields visible on F.Silkscreen.** They get *plotted*.
`write_lcsc_fields.py` hides them and moves them to F.Fab; if you add fields
elsewhere, do the same or part numbers end up printed on the boards.

**Never text-edit a `.kicad_*` file.** They are serialised object graphs with
UUIDs and cross-references. Go through `pcbnew` or the KiCad tooling.

## Removed scripts

These were superseded and deleted; the git history has them if needed.

| Was | Superseded by | Why |
|---|---|---|
| `pick_parts.py` | `jlc_search.py` | keyword search returned a thermistor for a 12.4k resistor |
| `pick_passives.py`, `pick_rest.py` | `jlc_search.py` | iterations toward type-validated matching |
| `stitch_vias.py`, `fix_drc.py` | `stitch2.py` | pads modelled as circles, inner layers and hole-to-hole ignored |
| `make_fab.py` | `run_vendor_toolkits.py` | hand-built vendor formats; the vendors' own plugins do it properly |
