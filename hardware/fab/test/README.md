# dbCANary rev A — test files: what to send where

Claims below were taken from JLCPCB's own help centre, blog and order form,
then independently re-checked against the live pages. Where JLCPCB contradicts
itself — and on the most important question, it does — that is called out
rather than smoothed over.

---

## 0. ⚠ Before you plan anything: JLCPCB's site contradicts itself on FCT

Two JLCPCB pages disagree about whether functional testing is offered at all:

| Page | Date | Says |
|---|---|---|
| Help: *Functional Test (FCT) Service* | Jun 10, 2026 | documents the service, checkout control, and pricing |
| Blog: *PCB functional testing guide* | **Jul 08, 2026** (newer) | verbatim: *"Q: Does JLCPCB perform functional testing on my boards? **No.** JLCPCB does not run functional testing; FCT is performed by you or a dedicated test house."* |

The **newer** page denies the service exists. The older help article describes
it in detail, with a screenshot.

**Do not commit to a schedule that depends on JLCPCB FCT until you have
confirmed with support that it is live.** Ask them directly, quoting the help
article. Everything in §3 below is conditional on that answer.

The rest of this document (flying probe, file formats) is unaffected.

---

## 1. Bare PCB electrical test — **no file needed**

The quote form's Electrical Test field, in the default 2-layer FR-4 config,
renders **exactly one selectable button: "Flying Probe Fully Test"**, already
selected. It is bundled into the quoted price.

> The "Full Test vs free Random Test" distinction, and "E-test Fixture",
> appear **only in the explanatory tooltip** describing test methods in
> general. They are not selectable options on a standard prototype order.
> (I had this wrong in the first draft of this document.)

Connectivity is CAM-extracted from the Gerber + drill set you upload. The order
form contains zero occurrences of "netlist", "IPC-D-356" or "D356".

**Action: nothing extra to do.** `jlcpcb/dbcanary-jlcpcb-netlist.ipc` already covers it.

---

## 2. Should you include the IPC-D-356 netlist? — optional, harmless, slightly favoured

My first draft said flatly that JLCPCB "does not accept" IPC-D-356. That was
**overstated**. The accurate position:

- There is **no dedicated netlist upload field**, and no help-centre page lists
  a netlist among required files.
- But JLCPCB's own blog, in a section that explicitly addresses their upload
  flow, answers *"What files do I need to send besides the Gerbers?"* with
  *"also include a drill map, an **IPC-D-356 netlist** for electrical
  verification, and a README…"*
- The uploader's "only zip or rar, max 100 MB" limit constrains the
  **container**, not its contents. Nothing states that an unrecognised file
  inside the ZIP is rejected or harmful.

**Recommendation: include `dbcanary.d356` in the Gerber ZIP.** It is 42 KB, it
cannot hurt, their own blog suggests it, and it gives their CAM a reference to
compare against rather than relying solely on extraction.

---

## 3. Functional test (FCT) — *if* it exists (see §0)

**This is not automated ATE.** JLCPCB's wording: *"the specific test methods
and functional criteria are defined and provided by the customer… JLCPCB
executes the tests strictly according to these specifications."* A human
operator powers the board up and follows a procedure **you** write.

| | |
|---|---|
| Where | checkout → Advanced Options → "Function test" (Yes/No + Attach) |
| **Order type** | **Standard PCBA only — NOT available on Economic** |
| Cost | ≈ USD 16 engineering + ≈ USD 8/hour operator labour |
| MOQ | none published (argument from silence — the page states no minimum) |
| You provide | product photos or DFM drawings, **detailed test procedure**, ideally a demo video |
| File format | not specified — a generic "Attach" button |
| Process | engineering review → they test board #1 → send you a video → you confirm by email → production continues |

**Send `FUNCTIONAL-TEST-SPEC.md` Part A.** Part B is in-house; do not send it.

### Three constraints to settle first

1. **This board is specced for Economic assembly.** The BOM/CPL were built
   SMD-top-only. FCT requires **Standard**. That changes the quote.
2. **Without FCT, JLCPCB does no power-on test at all** — their assembly T&C
   §3.3 says so explicitly. Skip it and the first energisation is on your bench.
3. **Assume you supply any test fixture.** The help article only hedges that
   JLCPCB "may support certain types"; the newer blog lists fixture, PSU, test
   controller and instruments as *the customer's* responsibility. Shipping a
   jig to them is undocumented — ask support.

### Programming is the *same* control, not a separate one

Firmware programming (≈ USD 8 engineering + ≈ USD 8/hour) has its own help
article, but it is **not a separate checkout option**: that article's own
instruction is *"select Advanced Options → Function test (Standard PCBA)"*,
and its screenshot is byte-identical to the FCT article's. One control covers
both; the distinction is in what you ask for and how it is quoted.

This matters because of the LED wiring:

| LED | Driven by | Lights without firmware? |
|---|---|---|
| **D304 ON** (green) | **3V3 rail via R305** | **YES** |
| D301 LAN / D302 ERR / D303 CAN | ESP32-S3 GPIO | no |

On an **unprogrammed** board an operator can verify exactly one LED. Either
buy programming so FCT tests something meaningful, or keep FCT minimal and
treat it as a power-integrity screen — which is what Part A is written as.

---

## 4. PCBA flying probe — **support-negotiated, not orderable**

Listed as item 14 on their Supported Personalized Services page. Important
qualifiers:

- It is the **only one of the 15 services with no published price**.
- It **does not appear in the PCBA order form** — there is no checkbox.
- The page's own instruction is *"If in doubt, consult JLCsupport."*

So: you cannot simply tick it and upload a file. **Contact support first.**

If they take it, the stated inputs are *"If designed with EDA, a PCBDOC file is
needed… If designed with other software, an **ODB++** file is needed."*
PCBDOC is Altium-native and **cannot be produced from KiCad**, so ODB++ is the
route — and JLCPCB's own linked ODB++ how-to is Altium's documentation.

| File | Size | Contains |
|---|---|---|
| `dbcanary-ODB++.zip` | 263 KB | all layers, drills, placement, **plus a CAD netlist with full untruncated net names** (`steps/pcb/netlists/cadnet/netlist`, 120 nets) |

---

## 5. Net-name truncation (why ODB++ is the better file)

IPC-D-356A has a fixed **14-character** net-name field. This board uses long
hierarchical sheet names, so `/Ethernet — W5500 …/ETH_CT_RD` is written as
`HERCON/ETH_CT_RD`. All 119 nets were checked: **no two collide**, so the file
is electrically correct — the names are just unreadable, and 50 contain an
em-dash rendered as `?`. `NETLIST-CROSSREF.csv` maps them back.

ODB++ has no such limit and keeps full names.

---

## 6. File index

| File | Send to | Purpose |
|---|---|---|
| `dbcanary.d356` | **inside the Gerber ZIP** (optional but suggested by JLCPCB's blog); required by PCBWay and most Western fabs | IPC-D-356A netlist |
| `dbcanary-ODB++.zip` | JLCPCB PCBA flying probe — **only after support agrees** | layers + full-name CAD netlist |
| `FUNCTIONAL-TEST-SPEC.md` **Part A** | JLCPCB FCT attachment — **only if §0 resolves** | operator-executable procedure |
| `BENCH-BRINGUP.md` | **in-house only** — never send this to a fab | full bench procedure: bench PSU, DMM, switch, scope, logic analyser, with expected values and annotated board drawings |
| `PROBE-POINTS.csv` / `.json` | in-house | every probe point, its pad, its net, its expected value and empty columns to record what you measured. Generated from the board by `hardware/scripts/probe_points.py` |
| `NETLIST-CROSSREF.csv` | reference | truncated → full net names, probe counts |
| `TEST-COVERAGE.md` | reference | what is testable, domain spacing |

---

## 7. Not established

- **Whether JLCPCB FCT is live at all** — see §0. Their two pages conflict.
- Whether you may ship them a physical test jig, and the customs/return path.
- Golden-sample boards: never mentioned on their site, neither required nor
  offered.
- Accepted file types / size limit for the FCT "Attach" button.
- Prices are as published and will drift; both "FCT" and the older name
  "Power-on Testing" are live on their site simultaneously, so quote either
  term to support.
- **No dbCANary board exists.** Nothing in the functional spec has been run,
  and nothing in `BENCH-BRINGUP.md` has been executed. Its `[predicted]` values
  are hypotheses, not acceptance limits.
