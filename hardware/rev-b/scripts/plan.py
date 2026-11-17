#!/usr/bin/env python3
"""
Rev B capture plan: what rev B adds to and changes in rev A's netlist.

hardware/rev-b/REV-B.md is the reasoning; this is the netlist it comes to. The
schematic is drawn from this through Konnect, and check_schematic.py proves the
drawn schematic is rev A's netlist plus exactly these changes:

    python3 -I hardware/rev-b/scripts/check_schematic.py

Every pin of every new part is on a net or listed in NC. Rev A nets are
named here by their rev A name; RENAMED says what each is called now.
"""

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
SOT235 = "Package_TO_SOT_SMD:SOT-353_SC-70-5"
SOT236 = "Package_TO_SOT_SMD:SOT-23-6"
PTC1206 = "Fuse:Fuse_1206_3216Metric"
HDR1x2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
HDR1x3 = "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"
MH = "MountingHole:MountingHole_3.2mm_M3"

MCU = "MCU — ESP32-S3-WROOM-1, USB, LEDs"
CAN = "dbCAN — ADM3053 isolated, 2x etherCON"
PWR = "Power — PoE + USB-C PD, 5V and 3V3"
ETH = "Ethernet — W5500 SPI, PoE magjack, etherCON"
EXP = "Expansion — front-panel header, port pads, mounting"

# Rev A nets that change name. Local MCU nets the expansion sheet needs become
# global; the LED anode nets lose their wrong _K suffix (rev B list).
RENAMED = {
    f"/{MCU}/EN": "EN",
    f"/{MCU}/BOOT": "BOOT",
    f"/{MCU}/LED_LAN": "LED_LAN",
    f"/{MCU}/LED_ERR": "LED_ERR",
    f"/{MCU}/LED_CAN": "LED_CAN",
    f"/{MCU}/LED_LAN_K": f"/{MCU}/LED_LAN_A",
    f"/{MCU}/LED_ERR_K": f"/{MCU}/LED_ERR_A",
    f"/{MCU}/LED_CAN_K": f"/{MCU}/LED_CAN_A",
    f"/{MCU}/LED_ON_K": f"/{MCU}/LED_ON_A",
}

# Rev A pins that move to another net. VCC_5V now comes out of the power mux,
# so the fuse output and the CH224K's supply and VBUS sense stay on the USB
# side. Each Bob Smith 75R gets its own DC-blocking capacitor for PoE: three
# on the BOB_SMITH side, R403's on its line side, where there was room.
MOVED = {
    ("F101", "2"): f"/{PWR}/VBUS_FUSED",
    ("R106", "1"): f"/{PWR}/VBUS_FUSED",
    ("R107", "1"): f"/{PWR}/VBUS_FUSED",
    ("R402", "2"): f"/{ETH}/BS_TD",
    ("R403", "1"): f"/{ETH}/BS_RD",
    ("R404", "2"): f"/{ETH}/BS_SPARE_1",
    ("R405", "2"): f"/{ETH}/BS_SPARE_2",
}

# Rev A parts that become another part on the same footprint: the PT61017PEL
# has no PoE rating; the B1608S is rated for PoE+ and shares its pinout and
# land pattern (pads 0.06 mm further out than the B1608S drawing asks).
# The N8R2 is the same module with 2 MB of quad PSRAM, for a planned
# remote-access client: quad PSRAM shares the flash bus inside the
# module, so it takes no GPIO, and it keeps the N8's -40 to 85 C rating, which
# the octal-PSRAM R8 modules do not (65 C; datasheet v1.8).
CHANGED = {
    "T401": {"value": "B1608S"},
    "U301": {"value": "ESP32-S3-WROOM-1-N8R2"},
}

# ref: (sheet, lib_id, value, footprint, {pin: net}, fields)
PARTS = {}


def part(ref, sheet, lib, value, fp, pins, **fields):
    PARTS[ref] = (sheet, lib, value, fp, pins, fields)


L = f"/{EXP}/"      # expansion-sheet local nets
P = f"/{PWR}/"
C = f"/{CAN}/"
E = f"/{ETH}/"

# ---------------------------------------------------------------- expansion
# Front-panel header J501. Every LED line is an open-drain SINK: the panel
# wires LED + resistor from FP_5V (or FP_3V3) into the pin. Same sense as the
# board LEDs: lit when the firmware drives the GPIO high.
for ref, src, out in (("U501", "VCC_3V3", "FP_ON_N"), ("U502", "LED_LAN", "FP_LAN_N"),
                      ("U503", "LED_CAN", "FP_CAN_N"), ("U504", "LED_ERR", "FP_ERR_N")):
    part(ref, EXP, "74xGxx:74LVC1G06", "74LVC1G06", SOT235,
         {"2": src, "3": "GND", "4": L + out, "5": "VCC_3V3"})
for i in range(1, 5):
    part(f"C50{i}", EXP, "Device:C", "100nF", C0402, {"1": "VCC_3V3", "2": "GND"})

part("F501", EXP, "Device:Polyfuse", "PTC 0.35A", PTC1206, {"1": "VCC_5V", "2": L + "FP_5V"})
part("F502", EXP, "Device:Polyfuse", "PTC 0.2A", PTC1206, {"1": "VCC_3V3", "2": L + "FP_3V3"})

# Reset: a bridged jumper a builder can cut to take EN off the ribbon.
part("R501", EXP, "Device:R", "100R", R0402, {"1": "EN", "2": L + "FP_RST_R"})
part("JP501", EXP, "Jumper:SolderJumper_2_Bridged", "FP_RESET",
     "Jumper:SolderJumper-2_P1.3mm_Bridged_RoundedPad1.0x1.5mm",
     {"1": L + "FP_RST_R", "2": L + "FP_RESET_N"})
part("R502", EXP, "Device:R", "100R", R0402, {"1": "BOOT", "2": L + "FP_BOOT_N"})
part("R503", EXP, "Device:R", "10k", R0402, {"1": "VCC_3V3", "2": "BOOT"})
part("R504", EXP, "Device:R", "10k", R0402, {"1": "VCC_3V3", "2": "FN1"})
part("R505", EXP, "Device:R", "10k", R0402, {"1": "VCC_3V3", "2": "FN2"})
part("R506", EXP, "Device:R", "100R", R0402, {"1": "FN1", "2": L + "FP_FN1"})
part("R507", EXP, "Device:R", "100R", R0402, {"1": "FN2", "2": L + "FP_FN2"})
part("R508", EXP, "Device:R", "4.7k", R0402, {"1": "VCC_3V3", "2": "I2C_SDA"})
part("R509", EXP, "Device:R", "4.7k", R0402, {"1": "VCC_3V3", "2": "I2C_SCL"})
part("R510", EXP, "Device:R", "100R", R0402, {"1": "I2C_SDA", "2": L + "FP_SDA"})
part("R511", EXP, "Device:R", "100R", R0402, {"1": "I2C_SCL", "2": L + "FP_SCL"})

# Channels grouped by where the lines leave J501: U505 takes the I2C and FN
# lines and RESET (top of the header as placed), U506 the LED sinks and BOOT.
part("U505", EXP, "Power_Protection:ESDA6V1-5SC6", "ESDA6V1-5SC6", SOT236,
     {"1": L + "FP_RESET_N", "2": "GND", "3": L + "FP_SCL", "4": L + "FP_FN1",
      "5": L + "FP_FN2", "6": L + "FP_SDA"})
part("U506", EXP, "Power_Protection:ESDA6V1-5SC6", "ESDA6V1-5SC6", SOT236,
     {"1": L + "FP_BOOT_N", "2": "GND", "3": L + "FP_ON_N", "4": L + "FP_LAN_N",
      "5": L + "FP_CAN_N", "6": L + "FP_ERR_N"})

J501 = ["FP_5V", "FP_3V3", "GND", "GND", "FP_ON_N", "FP_LAN_N", "FP_CAN_N", "FP_ERR_N",
        "FP_RESET_N", "FP_BOOT_N", "GND", "GND", "FP_SDA", "FP_SCL", "FP_FN1", "FP_FN2"]
part("J501", EXP, "Connector_Generic:Conn_02x08_Odd_Even", "FRONT PANEL",
     "Connector_IDC:IDC-Header_2x08_P2.54mm_Vertical_SMD",
     {str(i + 1): (n if n == "GND" else L + n) for i, n in enumerate(J501)})

# USB data pads, no VBUS and no CC: tying a second receptacle's VBUS to J102's
# would join two sources. DNP.
part("J502", EXP, "Connector_Generic:Conn_01x03", "USB DATA", HDR1x3,
     {"1": "USB_DM", "2": "USB_DP", "3": "GND"}, Fit="DNP")

for i in range(1, 5):
    part(f"H50{i}", EXP, "Mechanical:MountingHole", "M3", MH, {})

# ---------------------------------------------------------------- dbCAN pads
# Isolated side: these stay inside the CAN_GND domain at layout. DNP.
part("J203", CAN, "Connector_Generic:Conn_01x03", "CAN BUS", HDR1x3,
     {"1": C + "CANH", "2": C + "CANL", "3": C + "CAN_GND"}, Fit="DNP")
part("J204", CAN, "Connector_Generic:Conn_01x03", "TERM REMOTE", HDR1x3,
     {"1": C + "TERM_A", "2": C + "TERM_MID", "3": C + "TERM_B"}, Fit="DNP")

# ---------------------------------------------------------------- power
# VCC_5V comes out of U105, a TPS2116 power mux in priority mode: VIN1 is
# EXT_5V (PoE, or the auxiliary input through U106), VIN2 is USB. R108/R109
# hand over to USB when EXT_5V falls to about 4.0 V (VREF 1.0 V).
part("U105", PWR, "Power_Management:TPS2116DRL", "TPS2116", "Package_TO_SOT_SMD:SOT-583-8",
     {"1": "GND", "2": "VCC_5V", "3": "EXT_5V", "4": P + "MUX_PR1", "5": "EXT_5V",
      "6": P + "VBUS_FUSED", "7": "VCC_5V"})
part("R108", PWR, "Device:R", "100k", R0402, {"1": "EXT_5V", "2": P + "MUX_PR1"})
part("R109", PWR, "Device:R", "33k", R0402, {"1": P + "MUX_PR1", "2": "GND"})
part("C112", PWR, "Device:C", "1uF", C0402, {"1": "EXT_5V", "2": "GND"})
part("C110", PWR, "Device:C", "1uF", C0402, {"1": P + "VBUS_FUSED", "2": "GND"})
part("J103", PWR, "Connector_Generic:Conn_01x02", "5V AUX IN", HDR1x2,
     {"1": P + "VIN_AUX", "2": "GND"}, Fit="DNP")
part("F102", PWR, "Device:Polyfuse", "PTC 1.1A", PTC1206, {"1": P + "VIN_AUX", "2": P + "AUX_FUSED"})
part("D105", PWR, "Device:D_Zener", "SMF5.0A", "Diode_SMD:D_SOD-123F", {"1": P + "AUX_FUSED", "2": "GND"})
part("U106", PWR, "Power_Management:LM66100DCK", "LM66100", "Package_TO_SOT_SMD:SOT-363_SC-70-6",
     {"1": P + "AUX_FUSED", "2": "GND", "3": "GND", "6": "EXT_5V"})
part("C111", PWR, "Device:C", "1uF", C0402, {"1": P + "AUX_FUSED", "2": "GND"})

# ---------------------------------------------------------------- ethernet
part("R413", ETH, "Device:R", "10k", R0402, {"1": "VCC_3V3", "2": "ETH_RSTn"})

# PoE powered device. D401 takes mode A (T401's centre taps), D402 mode B (the
# spare pairs), D403 clamps the rectified input, U402 is the isolated
# 802.3af module. POE_VP/POE_VN float against GND and CHASSIS.
C10N = "10nF 100V"
part("C414", ETH, "Device:C", C10N, C0402, {"1": E + "BS_TD", "2": E + "BOB_SMITH"})
part("C415", ETH, "Device:C", C10N, C0402, {"1": E + "BS_RD", "2": E + "ETH_CT_RD"})
part("C416", ETH, "Device:C", C10N, C0402, {"1": E + "BS_SPARE_1", "2": E + "BOB_SMITH"})
part("C417", ETH, "Device:C", C10N, C0402, {"1": E + "BS_SPARE_2", "2": E + "BOB_SMITH"})
BRIDGE, TO269 = "Device:D_Bridge_+-AA", "Package_TO_SOT_SMD:TO-269AA"
part("D401", ETH, BRIDGE, "MB10S", TO269,
     {"1": E + "POE_VP", "2": E + "POE_VN", "3": E + "ETH_CT_RD", "4": E + "ETH_CT_TD"})
part("D402", ETH, BRIDGE, "MB10S", TO269,
     {"1": E + "POE_VP", "2": E + "POE_VN", "3": E + "ETH_SPARE_1", "4": E + "ETH_SPARE_2"})
part("D403", ETH, "Device:D_Zener", "SMAJ58A", "Diode_SMD:D_SMA", {"1": E + "POE_VP", "2": E + "POE_VN"})
part("U402", ETH, "canary:DP9900M-5V", "DP9900M-5V", "canary:SDAPO_DP9900M",
     {"1": "EXT_5V", "2": "EXT_5V", "3": "GND", "5": E + "POE_VP", "6": E + "POE_VP",
      "7": E + "POE_VN", "8": E + "POE_VN"})
part("C418", ETH, "Device:C", "47uF", "Capacitor_SMD:C_1206_3216Metric", {"1": "EXT_5V", "2": "GND"})
part("C419", ETH, "Device:C", "100nF", C0402, {"1": "EXT_5V", "2": "GND"})

# ---------------------------------------------------------------- sourcing
# LCSC part for every fitted new part, written into the schematic as LCSC /
# MPN / Manufacturer fields (check_schematic.py holds them to this) and onto
# the board by sync.py, where the JLC toolkit reads them. Rev A's own parts
# keep the fields rev A's write_lcsc_fields.py put on its board. JP501, the
# holes and the DNP pads have none.
PART_NUMBERS = {   # LCSC: (MPN, manufacturer)
    "C1525": ("CL05B104KO5NNNC", "Samsung"),          # 100nF 0402, rev A's
    "C52923": ("CL05A105KA5NQNC", "Samsung"),         # 1uF 0402, rev A's
    "C527014": ("CC0402KRX7R0BB103", "YAGEO"),        # 10nF 100V 0402
    "C96123": ("CL31A476MPHNNNE", "Samsung"),         # 47uF 10V 1206
    "C25076": ("0402WGF1000TCE", "UNI-ROYAL"),        # 100R
    "C25744": ("0402WGF1002TCE", "UNI-ROYAL"),        # 10k, rev A's
    "C25900": ("0402WGF4701TCE", "UNI-ROYAL"),        # 4.7k
    "C25741": ("0402WGF1003TCE", "UNI-ROYAL"),        # 100k
    "C25779": ("0402WGF3302TCE", "UNI-ROYAL"),        # 33k
    "C910827": ("BSMD1206-035-16V", "BHFUSE"),
    "C883118": ("BSMD1206-020-30V", "BHFUSE"),
    "C21714343": ("BSMD1206-110-30V", "BHFUSE"),      # rev A's F101
    "C7828": ("SN74LVC1G06DCKR", "Texas Instruments"),
    "C2970918": ("ESDA6V1-5SC6Y", "STMicroelectronics"),
    "C19190396": ("BH254VS-16P", "XFCN"),
    "C3235557": ("TPS2116DRLR", "Texas Instruments"),
    "C2869734": ("LM66100DCKR", "Texas Instruments"),
    "C193402": ("SMF5.0A", "MDD"),
    "C5380106": ("DP9900M-5V", "SDAPO"),
    "C2488": ("MB10S-50MIL", "MDD"),
    "C123816": ("SMAJ58A", "MDD"),
    "C507596": ("B1608S", "CND-tek"),
}
LCSC = {
    **{r: "C1525" for r in ("C501", "C502", "C503", "C504", "C419")},
    **{r: "C52923" for r in ("C110", "C111", "C112")},
    **{r: "C527014" for r in ("C414", "C415", "C416", "C417")},
    "C418": "C96123",
    **{r: "C25076" for r in ("R501", "R502", "R506", "R507", "R510", "R511")},
    **{r: "C25744" for r in ("R413", "R503", "R504", "R505")},
    "R508": "C25900", "R509": "C25900", "R108": "C25741", "R109": "C25779",
    "F501": "C910827", "F502": "C883118", "F102": "C21714343",
    **{r: "C7828" for r in ("U501", "U502", "U503", "U504")},
    "U505": "C2970918", "U506": "C2970918", "J501": "C19190396",
    "U105": "C3235557", "U106": "C2869734", "D105": "C193402",
    "U402": "C5380106", "D401": "C2488", "D402": "C2488", "D403": "C123816",
}
for _ref, _code in LCSC.items():
    _mpn, _maker = PART_NUMBERS[_code]
    PARTS[_ref][5].update(LCSC=_code, MPN=_mpn, Manufacturer=_maker)
CHANGED["T401"].update(LCSC="C507596", MPN="B1608S", Manufacturer="CND-tek")
CHANGED["U301"].update(LCSC="C2913204", MPN="ESP32-S3-WROOM-1-N8R2",
                       Manufacturer="Espressif Systems")

# Pins with nothing on them: the TPS2116's ST status output, the LM66100's ST
# and NC pins, and the DP9900M's output trim (ADJ open = 5.00 V).
NC = {("U105", "8"), ("U106", "4"), ("U106", "5"), ("U402", "4")}

# U301 GPIOs rev A left no-connect that rev B uses.
U301 = {"39": "I2C_SDA", "38": "I2C_SCL", "31": "FN1", "32": "FN2"}

if __name__ == "__main__":
    print(f"{len(PARTS)} new parts, {len(RENAMED)} renamed nets, {len(MOVED)} moved pins, "
          f"{len(CHANGED)} changed parts")
