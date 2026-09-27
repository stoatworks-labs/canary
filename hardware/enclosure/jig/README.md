# CANary — heat-set insert jig

Output of `hardware/enclosure/gen_insert_jig.py`: three PLA parts that hold the one-piece
tube ([`../3dp-tube/`](../3dp-tube/README.md)) upright on the bed of duck.knapp's
**Heat Set Insert Press (99% 3D-Printed)** (MakerWorld, CC BY-NC-SA — the press itself is
not in this repo; only measurements of its base are) and put each of the tube's eight
insert pilots under the iron's tip in turn. Sliced as `../canary-insert-jig-pla-0.4-jig.3mf`
(`bambu/build.sh pla-0.4-jig jig`).

| Part | What it is |
|---|---|
| `canary_jig_plate` | 208 × 208 × 4 mm index plate. Two straight edges sit against the inside faces of the press's L-shaped wall, which fixes it; the corner is cut to the wall's R50. Eight keyed sockets, labelled F1–F4 / R1–R4, a legend, and a countersunk Ø2.5 hole **exactly under the tip**. |
| `canary_jig_nest` | Cradle the tube stands in, end down: 3 mm floor, 12 mm collar, 0.3 mm clear of the tube. Ø7 reliefs under every pilot either end can present, so inserts already pressed into the lower end cannot rock it. Two keyed holes, **F** and **R**, and a V notch in the collar at the **press end**. |
| `canary_jig_peg` | One loose keyed peg (5 mm square, one corner chamfered, 9 mm cap). It fits the nest's holes and the plate's sockets one way only. Printed cap-down. |

## Using it

1. Set the plate on the bed, pushed into the L's inside corner against both walls.
   Lower the cold tip: it should land in the countersunk hole. If it does not, see
   *The tip position* below before pressing anything.
2. Stand the tube in the nest with the end you are doing **up**. The **front** end is the
   etherCON end; the **rear** end is the one nearest the LED window.
3. Turn the tube so the insert you want is at the nest's **notched end**. Only one of the
   two ways round puts it there.
4. Peg in the nest's **F** hole with the front end up, **R** with the rear end up.
5. Drop the peg into that insert's socket (table below). The nest lies along the bed's
   diagonal with the notched end toward the L's corner and the rest of the tube hanging
   out toward the open side.
6. Insert on the tip, lower it onto the pilot, press.

"Left"/"right" are as seen from outside that end with the lid (the face with the lettering)
on top. "Boss" is the round Ø9 / Ø7 column under the lid; "rail" is the board rail near the
base.

| Socket | End up | Insert |
|---|---|---|
| F1 | front | right boss |
| F2 | front | right rail |
| F3 | front | left boss |
| F4 | front | left rail |
| R1 | rear | left boss |
| R2 | rear | left rail |
| R3 | rear | right boss |
| R4 | rear | right rail |

The engraved labels read the right way up from where you stand to use the press — at the
open side of the bed, facing the L's corner.

## Why always the corner end

The tube is 137 mm long and its pilots sit 50–60 mm off its centre, so with any pilot under
the tip the far end of the tube is ~130 mm away. Toward the L's corner there are only
~100 mm before the wall; toward the open side of the bed there is room. So every insert is
pressed with its end of the tube toward the corner and the rest hanging forward. That is
also why there are two peg holes: pressing the front end's inserts and the rear end's puts
the nest in eight different places, and two pairs of them are only 2–3 mm apart. Moving the
peg 20 mm between F and R separates the two sets; the closest two sockets still leave a
2.5 mm web.

## The tip position — MEASURE ME

`TIP_FROM_WALL` in the generator is the distance from the tip's axis to the inside face of
each wall. The press's linkage is symmetric, so the tip comes down on the L's diagonal, but
how far along it depends on the iron and how it sits in the clamp. **The default, 86.7 mm,
is an estimate** from the model and the designer's photos (iron axis ~24 mm in front of the
arm plane), not a measurement. With the press built:

1. lower the tip to the bed and measure from its axis to each wall's inside face;
2. rebuild: `<venv>/bin/python hardware/enclosure/gen_insert_jig.py --tip X Y`, then
   `bambu/build.sh pla-0.4-jig jig` (the plate is the only part that changes).

## How it is checked

The generator poses the real, exported (mirrored) tube in the nest for each of the eight
sockets and probes the built solid: nothing within 1.2 mm of the tip's axis in the top
3 mm (an open pilot) and material in a ring at r 2.9 mm (the boss or rail around it). It
also checks that the tube and nest stay clear of the wall and its corner arc, that the nest
sits wholly on the plate, that the peg drops into each socket and fits the nest's hole,
that the peg's cap is clear of the tube's wall, and that every label is next to its own
socket and clear of the others. Swapping the front-end pilot mapping makes six of the
eight sockets fail.

## Not yet known

* **Nothing here has been printed**, and the press was not built when this was designed.
* **Height.** The tube's top face stands **95.5 mm** above the bed (4 mm plate + 3 mm floor
  + 88.5 mm tube). The tip, with an insert on it, has to start above that. The press's arms
  come in different lengths for exactly this; use the longer set if the shorter one cannot
  lift the tip that high.
* The tip position above.
