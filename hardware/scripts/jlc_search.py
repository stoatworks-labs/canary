#!/usr/bin/env python3
"""
Fill the remaining BOM lines from JLCPCB's own parts API.

This is the same endpoint kicad-jlcpcb-tools uses. Unlike jlcsearch it pages
past 100 results and reports componentLibraryType (base/expand) directly.

Every candidate is validated against the fields JLCPCB returns - value string
anchored at the start of the ERP name, package, component TYPE (so a
thermistor can never satisfy a resistor line again), and where it matters,
dielectric, hold current or LED colour (Chinese label; 红外 = infrared is
explicitly excluded from 'red'). Base parts outrank extended; stock breaks
ties. Nothing is written unless a validator passes.
"""
import json, re, sys, time, urllib.request

API = ("https://jlcpcb.com/api/overseas-pcb-order/v1/"
       "shoppingCart/smtGood/selectSmtComponentList")


def search(keyword, pages=2, size=50):
    out = []
    for page in range(1, pages + 1):
        body = json.dumps({"currentPage": page, "pageSize": size,
                           "keyword": keyword, "componentLibraryType": "",
                           "stockFlag": False, "searchSource": "search"}).encode()
        req = urllib.request.Request(API, data=body, headers={
            "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.load(r)
        except Exception as e:
            print(f"    API error {e} for {keyword!r}", file=sys.stderr)
            return out
        lst = (((d.get("data") or {}).get("componentPageInfo") or {})
               .get("list") or [])
        out += lst
        if len(lst) < size:
            break
        time.sleep(0.4)
    return out


def rank(c):
    return (-int(c.get("componentLibraryType") == "base"),
            -(c.get("stockCount") or 0))


def val_res(name_start):
    def f(c):
        n = c.get("erpComponentName") or ""
        return (n.startswith(name_start)
                and "Resistor" in (c.get("componentTypeEn") or "")
                and "Thermistor" not in (c.get("componentTypeEn") or ""))
    return f


def val_cap(prefix, need=(), vmin=16):
    def f(c):
        n = c.get("erpComponentName") or ""
        if not n.startswith(prefix):
            return False
        if "Capacitor" not in (c.get("componentTypeEn") or ""):
            return False
        if need and not any(k in n for k in need):
            return False
        m = re.search(r"(\d+(?:\.\d+)?)V", n)
        return bool(m) and float(m.group(1)) >= vmin
    return f


def val_led(colour_yes, colour_no=()):
    def f(c):
        n = c.get("erpComponentName") or ""
        t = c.get("componentTypeEn") or ""
        if "Light Emitting" not in t and "LED" not in t:
            return False
        if any(k in n for k in colour_no):
            return False
        return any(k in n for k in colour_yes)
    return f


def val_type(type_key, need_name=()):
    def f(c):
        t = c.get("componentTypeEn") or ""
        n = c.get("erpComponentName") or ""
        return type_key in t and all(k in n for k in need_name)
    return f


def val_mpn(mpn):
    def f(c):
        return (c.get("componentModelEn") or "").upper() == mpn.upper()
    return f


# (BOM Comment, keyword(s), package or None, validator)
JOBS = [
    ("12.4k 1%",  ["12.4k 0402"],            "0402", val_res("12.4kΩ ±1%")),
    ("31.6k 1%",  ["31.6k 0402"],            "0402", val_res("31.6kΩ ±1%")),
    # The API's keyword match works best on value-with-unit or on the
    # manufacturer's own series coding (E96 code 4992 = 49.9, 620/750 = E24).
    ("49.9R 1%",  ["49.9Ω 0402", "0402WGF4992", "49R9 0402"],
                                             "0402", val_res("49.9Ω ±1%")),
    ("62R",       ["62Ω 0603", "0603WAF620J", "62R 0603"],
                                             "0603", val_res("62Ω")),
    ("75R",       ["75Ω 0603", "0603WAF750J", "75R 0603"],
                                             "0603", val_res("75Ω")),
    ("18pF",      ["18pF 0402 C0G", "0402CG180", "18pF 0402"],
                                             "0402", val_cap("18pF", ("C0G", "NP0"), 25)),
    ("4.7nF",     ["4.7nF 0603"],            "0603", val_cap("4.7nF", (), 16)),
    ("6.8nF (RCT)", ["6.8nF 0402"],          "0402", val_cap("6.8nF", (), 16)),
    # Murata BLM18AG601 / Sunlord GZ1608 are the standard 0603 600R beads;
    # search by MPN prefix since the value keyword finds nothing.
    ("600R@100MHz", ["BLM18AG601SN1D", "GZ1608U601TF", "600R 0603 磁珠"],
                                             "0603", val_type("Ferrite", ("600",))),
    ("PTC 1.1A",  ["1.1A 1206 PTC", "1206 resettable fuse 1.1A"],
                                             "1206", val_type("Resettable", ("1.1A",))),
    # The red line matched via its Chinese label (0603 红灯), so query the
    # greens the same way. 翠绿 = emerald/pure green; 黄绿 (yellow-green) and
    # 红外 (infrared) are excluded.
    ("LAN (green)", ["0603 绿灯", "KT-0603 绿", "翠绿 0603"],
                                             "0603", val_led(("绿",), ("红外", "黄绿"))),
    ("CAN (green)", ["0603 绿灯"],           "0603", val_led(("绿",), ("红外", "黄绿"))),
    ("ON (green)",  ["0603 绿灯"],           "0603", val_led(("绿",), ("红外", "黄绿"))),
    ("ERR (red)",   ["0603 LED red"],        "0603", val_led(("红", "Red", "red"), ("红外",))),
    ("ESP32-S3-WROOM-1-N8", ["ESP32-S3-WROOM-1-N8"], None,
                                             val_mpn("ESP32-S3-WROOM-1-N8")),
    ("USB-C 16P", ["TYPE-C-31-M-12"],        None,
     lambda c: "TYPE-C-31-M-12" in (c.get("componentModelEn") or "").upper()),
]


def main():
    picks = {}
    for label, kws, pkg, ok in JOBS:
        best = None
        for kw in kws:
            cands = [c for c in search(kw) if c.get("stockCount")
                     and (pkg is None
                          or c.get("componentSpecificationEn") == pkg)
                     and ok(c)]
            cands.sort(key=rank)
            if cands:
                best = cands[0]
                break
            time.sleep(0.4)
        if best:
            picks[label] = {
                "code": best["componentCode"],
                "mpn": best.get("componentModelEn", ""),
                "brand": best.get("componentBrandEn", ""),
                "lib": best.get("componentLibraryType", ""),
                "stock": best.get("stockCount", 0),
                "name": (best.get("erpComponentName") or "")[:44],
            }
            p = picks[label]
            print(f"  {label:<20} {p['code']:<10} {p['lib']:<6} "
                  f"{str(p['stock']):>9}  {p['mpn'][:26]:<26} {p['name']}")
        else:
            print(f"  {label:<20} {'--':<10} NO VALIDATED MATCH")
        time.sleep(0.4)
    json.dump(picks, open("/tmp/jlc_picks.json", "w"),
              indent=1, ensure_ascii=False)
    print(f"\nmatched {len(picks)}/{len(JOBS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
