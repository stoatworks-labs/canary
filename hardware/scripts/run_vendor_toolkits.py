#!/usr/bin/env python3
"""
Drive the vendor Fabrication Toolkit plugins headlessly.

Both plugins are written for the pcbnew GUI: they call `pcbnew.GetBoard()`,
which returns None outside it. Rather than reimplement their output formats,
this loads the board with LoadBoard() and monkeypatches GetBoard() to return
it - so the plugins' own, vendor-maintained generators run unmodified and we
inherit their conventions instead of guessing at them.

DELIBERATELY NOT DONE: PCBWay's own thread uploads the generated archive to
pcbway.com after building it. Only the file-generation methods are called here.
Sending the design to an external service is the user's decision, not a side
effect of regenerating outputs.

Usage:
  <kicad python> run_vendor_toolkits.py [jlc|pcbway|both]
"""
import os as _os
_REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os
import shutil
import sys
import tempfile

import pcbnew

HW = _REPO + "/hardware"
BOARD = f"{HW}/dbcanary.kicad_pcb"
PLUGINS = os.path.expanduser("~/Documents/KiCad/10.0/3rdparty/plugins")
JLC_PLUGIN = f"{PLUGINS}/com_github_bennymeg_JLC-Plugin-for-KiCad"
PW_PLUGIN = f"{PLUGINS}/com_github_pcbway_PCBWay-Fabrication-Toolkit-for-KiCad"


def _alias_plugins():
    """Plugin dirs contain hyphens, which are illegal in module names."""
    tmp = tempfile.mkdtemp(prefix="kicad-plugins-")
    for target, name in ((JLC_PLUGIN, "fabtoolkit"), (PW_PLUGIN, "pcbwaytoolkit")):
        if os.path.isdir(target):
            os.symlink(target, os.path.join(tmp, name))
    sys.path.insert(0, tmp)
    return tmp


def run_pcbway(board):
    """Generate PCBWay's gerber archive, netlist and components CSV."""
    out = f"{HW}/fab/pcbway-toolkit"
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(f"{out}/gerber", exist_ok=True)

    # The plugin reads the board from the GUI singleton; give it ours.
    pcbnew.GetBoard = lambda: board

    from pcbwaytoolkit.process import PCBWayProcess
    p = PCBWayProcess()
    p.get_gerber_file(f"{out}/gerber")
    p.get_netlist_file(out + "/")
    p.get_components_file(out + "/")

    archive = shutil.make_archive(f"{out}/dbcanary_gerber", "zip", f"{out}/gerber")
    print(f"  PCBWay: gerbers -> {os.path.basename(archive)}")
    for f in sorted(os.listdir(out)):
        if os.path.isfile(os.path.join(out, f)):
            print(f"          {f}  ({os.path.getsize(os.path.join(out, f))} bytes)")
    return out


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    _alias_plugins()
    board = pcbnew.LoadBoard(BOARD)

    if which in ("pcbway", "both"):
        if not os.path.isdir(PW_PLUGIN):
            print("  PCBWay toolkit not installed, skipping")
        else:
            run_pcbway(board)

    if which in ("jlc", "both"):
        print("  JLC: run via its own CLI, which handles this properly:")
        print("       PYTHONPATH=<alias dir> python -m fabtoolkit.cli "
              "--path <board> --autoTranslate --autoFill --excludeDNP "
              "--nonInteractive --noBackup")
    return 0


if __name__ == "__main__":
    sys.exit(main())
