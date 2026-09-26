# Sources

Primary documents this project was built from. They are **not committed** —
they are third-party copyrighted manuals, and dbCANary redistributes no vendor
material. Download them yourself; `docs/*.pdf` is gitignored so they can sit
here locally.

## The transport

- **RM Byte Command Protocol — API description**, RM Michaelides Software &
  Elektronik GmbH (now Proemion). The protocol the R70's Ethernet side speaks.
  A copy has been mirrored at
  `https://www.witree.co.kr/layouts/witree_2015/data/product/Manual/RM_Byte_Command_Manual.pdf`
  Proemion's own documentation portal: `https://docs.proemion.com/`

- **Device Manual CANlink WLAN Series 2000**, RM Michaelides. Confirms the RM
  Byte Command Protocol is carried as the payload of TCP/UDP frames and that
  several CAN messages are batched into one block.

## d&b audiotechnik

- **R70 Ethernet to CAN interface — Manual 1.4 EN** (DOC01816). Ports, default
  addressing, LEDs, physical spec.
- **R70 Ethernet to CAN interface — Software reference manual 1.3 EN**. Socket
  modes, CAN filtering, and the dbCAN identifier structure.
- **TI 312 — d&b Remote network 1.4 EN** (D5312.E.01). Bus topology, RJ45 and
  D-SUB9 pinouts, termination, cable limits, dbCAN-ID notation.

All three are published on `https://www.dbaudio.com` under the R70 product
downloads.

## Registries

- IEEE Individual Address Block registry,
  `https://standards-oui.ieee.org/iab/iab.txt` — identifies the R70's MAC block
  `00-50-C2 / 5DC000-5DCFFF` as RM Michaelides, which is what revealed the OEM.

## R1 itself

The UDP 33333 discovery protocol is not documented by the vendor. It is
documented here from captures of R1 V3.46's discovery traffic and confirmed live.
No R1 code is included — only the wire format needed to interoperate. See
`PROTOCOL.md` §4.

## Hardware / mechanical

- **Neutrik NE8FBH etherCON** — PCB-mount etherCON receptacle, the connector all
  three network jacks use. `hardware/lib/dbcanary.pretty/Neutrik_etherCON_NE8FBH.kicad_mod`
  was drawn from its DXF. The datasheet is **not committed**
  (`hardware/lib/*.pdf` is gitignored, same no-redistribution policy as above);
  download it from Neutrik and drop it at `hardware/lib/ne8fbh.pdf`.

  Worth having to hand: the footprint courtyard is ~14.4 mm but the real front
  plate is 25 mm, and the renders carry no 3D model for it — so the datasheet is
  the only way to check the mating face lines up with the board edge.

## Other manufacturers' control protocols

Moved to the **amp-commander** repo, which is where multi-brand and RS485 work
now lives. dbCANary is d&b-only.
