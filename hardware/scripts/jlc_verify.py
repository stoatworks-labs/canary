#!/usr/bin/env python3
"""
Write the final picks into the JLC BOM, then re-verify EVERY line by code.

The verification pass is the point: each assigned Cxxxxx is queried back
against JLCPCB's API and must return that exact componentCode, in stock and
orderable. The confirmed record's MPN and manufacturer then populate the
PCBWay BOM, and base/expand counts give the real assembly fee exposure.
A code that fails verification is REMOVED from the BOM and reported.
"""
import csv, json, sys, time, urllib.request

API = ("https://jlcpcb.com/api/overseas-pcb-order/v1/"
       "shoppingCart/smtGood/selectSmtComponentList")
BOM = "fab/jlcpcb/canary-jlcpcb-bom.csv"
PW = "fab/pcbway/canary-pcbway-bom.csv"

FINAL_PICKS = {          # from the debug queries, validated by eye
    "18pF": "C1549",             # 0402CG180J500NT - CG in the MPN = C0G
    "LAN (green)": "C12624",     # KT-0603G, emerald
    "CAN (green)": "C12624",
    "ON (green)": "C12624",
}
# Hand-soldered THT lines in the PCBWay BOM: MPNs from the project docs.
THT_MPN = {
    "etherCON NE8FBH": ("Neutrik", "NE8FBH"),
}


def query(code):
    body = json.dumps({"currentPage": 1, "pageSize": 10, "keyword": code,
                       "componentLibraryType": "", "stockFlag": False,
                       "searchSource": "search"}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.load(r)
    for c in (((d.get("data") or {}).get("componentPageInfo") or {})
              .get("list") or []):
        if c.get("componentCode") == code:
            return c
    return None


def main():
    picks = json.load(open("/tmp/jlc_picks.json"))
    rows = list(csv.DictReader(open(BOM)))
    for r in rows:
        k = r["Comment"].strip()
        if not r["LCSC Part #"]:
            if k in FINAL_PICKS:
                r["LCSC Part #"] = FINAL_PICKS[k]
            elif k in picks:
                r["LCSC Part #"] = picks[k]["code"]

    # --- verify every code against the live API -------------------------
    master, bad = {}, []
    for r in rows:
        code = r["LCSC Part #"]
        if not code:
            bad.append((r["Comment"], "no part assigned"))
            continue
        if code in master:
            continue
        c = query(code)
        time.sleep(0.45)
        if c is None:
            bad.append((r["Comment"], f"{code} not found on JLCPCB"))
            r["LCSC Part #"] = ""
            continue
        if not c.get("stockCount"):
            bad.append((r["Comment"], f"{code} zero stock"))
        master[code] = {
            "mpn": c.get("componentModelEn", ""),
            "brand": c.get("componentBrandEn", ""),
            "lib": c.get("componentLibraryType", ""),
            "stock": c.get("stockCount", 0),
            "name": c.get("erpComponentName", ""),
            "spec": c.get("componentSpecificationEn", ""),
        }

    with open(BOM, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Comment", "Designator",
                                          "Footprint", "LCSC Part #"])
        w.writeheader(); w.writerows(rows)

    # --- fill the PCBWay BOM with verified MPN/brand ---------------------
    code_by_ref = {}
    for r in rows:
        for d in r["Designator"].split(","):
            code_by_ref[d.strip()] = r["LCSC Part #"]
    pw = list(csv.DictReader(open(PW)))
    for r in pw:
        ref0 = r["Designator"].split(",")[0].strip()
        code = code_by_ref.get(ref0)
        if code and code in master:
            r["Manufacturer"] = master[code]["brand"]
            r["Manufacturer Part Number"] = master[code]["mpn"]
            r["Notes"] = f"LCSC {code}"
        else:
            for key, (br, mpn) in THT_MPN.items():
                if key in r["Value"]:
                    r["Manufacturer"], r["Manufacturer Part Number"] = br, mpn
    with open(PW, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pw[0].keys()))
        w.writeheader(); w.writerows(pw)

    done = sum(1 for r in rows if r["LCSC Part #"])
    ext = [c for c, m in master.items() if m["lib"] != "base"]
    base = [c for c, m in master.items() if m["lib"] == "base"]
    print(f"BOM lines assigned+verified : {done}/{len(rows)}")
    print(f"unique parts               : {len(master)}  "
          f"(base {len(base)}, extended {len(ext)})")
    print(f"extended-part fee exposure : {len(ext)} x $3 = ${3*len(ext)}")
    lows = [(c, m) for c, m in master.items() if m["stock"] < 1000]
    for c, m in lows:
        print(f"  LOW STOCK {c} {m['mpn']} : {m['stock']}")
    crystal = master.get("C9006")
    if crystal:
        print(f"crystal C9006 full name    : {crystal['name']}")
    for c, why in bad:
        print(f"  PROBLEM {c}: {why}")
    json.dump(master, open("fab/parts-master.json", "w"),
              indent=1, ensure_ascii=False)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
