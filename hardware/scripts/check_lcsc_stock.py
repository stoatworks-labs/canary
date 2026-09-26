#!/usr/bin/env python3
"""Resolve every LCSC part in a fab BOM against the live jlcsearch API.

Answers, per line: does the code still exist, is the MPN still the one we
specified, is there stock, and is it a JLCPCB basic or extended part.
"""
import csv, json, os, sys, time, urllib.request, urllib.parse

API = "https://jlcsearch.tscircuit.com/api/search"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lcsc_cache.json")
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}


def query(q):
    if q in cache:
        return cache[q]
    url = f"{API}?{urllib.parse.urlencode({'q': q, 'limit': 20, 'full': 'true'})}"
    # The API 403s a bare urllib request; it wants a browser-ish User-Agent.
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.7.1"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.load(r).get("components", [])
                cache[q] = out
                json.dump(cache, open(CACHE, "w"))
                time.sleep(0.5)
                return out
        except Exception as e:
            if attempt == 2:
                return {"error": str(e)}
            time.sleep(2)


def pick(row, *names):
    for n in names:
        for k, v in row.items():
            if k and k.strip().lower() == n.lower() and (v or "").strip():
                return v.strip()
    return ""


def norm(s):
    return "".join(c for c in (s or "").upper() if c.isalnum())


def check(path, label):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    out = []
    for r in rows:
        code = pick(r, "LCSC Part #", "LCSC")
        mpn = pick(r, "Manufacturer Part Number", "MPN")
        refs = pick(r, "Designator", "References", "Reference Designators")
        qty = pick(r, "Quantity", "Qty") or "?"
        if not code:
            out.append(dict(refs=refs, qty=qty, code="", mpn=mpn, status="NO LCSC CODE"))
            continue
        res = query(code)
        if isinstance(res, dict):
            out.append(dict(refs=refs, qty=qty, code=code, mpn=mpn, status=f"API ERROR {res['error']}"))
            continue
        hit = next((c for c in res if f"C{c['lcsc']}" == code.upper()), None)
        if not hit:
            out.append(dict(refs=refs, qty=qty, code=code, mpn=mpn, status="NOT FOUND"))
            continue
        stock = hit.get("stock") or 0
        basic = hit.get("is_basic")
        api_mpn = hit.get("mfr") or ""
        need = int(qty) if qty.isdigit() else 0
        flags = []
        if stock == 0:
            flags.append("ZERO STOCK")
        elif need and stock < need * 10:
            flags.append(f"LOW STOCK ({stock})")
        if mpn and api_mpn and norm(mpn) != norm(api_mpn):
            flags.append(f"MPN MISMATCH: BOM says {mpn}, LCSC says {api_mpn}")
        out.append(dict(refs=refs, qty=qty, code=code, mpn=mpn, api_mpn=api_mpn,
                        stock=stock, basic=basic, status="; ".join(flags) or "OK"))
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: check_lcsc_stock.py <bom.csv> [bom.csv ...]\n"
                 "  Resolves every LCSC part against the live jlcsearch API and\n"
                 "  reports stock, basic/extended, MPN drift, and how many boards\n"
                 "  the tightest line can currently build.")
    for path in sys.argv[1:]:
        print(f"\n{'='*104}\n{path}\n{'='*104}")
        rows = check(path, path)
        print(f"  {'refs':30s} {'lcsc':10s} {'qty':>4s} {'stock':>10s} {'type':9s} note")
        cap = []
        for r in rows:
            if r["status"] == "NO LCSC CODE":
                print(f"  {r['refs'][:29]:30s} {'-':10s} {r['qty']:>4s} {'-':>10s} {'-':9s} "
                      f"not an LCSC part ({r['mpn'] or 'no MPN'})")
                continue
            if "NOT FOUND" in r["status"] or "API ERROR" in r["status"]:
                print(f"  {r['refs'][:29]:30s} {r['code']:10s} {r['qty']:>4s} {'-':>10s} {'-':9s} {r['status']}")
                continue
            q = int(r["qty"]) if r["qty"].isdigit() else 1
            st = r.get("stock", 0)
            cap.append((st // max(q, 1), r["refs"]))
            note = "" if r["status"] == "OK" else r["status"]
            print(f"  {r['refs'][:29]:30s} {r['code']:10s} {r['qty']:>4s} {st:>10,d} "
                  f"{'basic' if r.get('basic') else 'extended':9s} {note}")
        if cap:
            cap.sort()
            print(f"\n  Tightest line: {cap[0][1].strip()} -> current LCSC stock builds "
                  f"{cap[0][0]:,} board(s)")
