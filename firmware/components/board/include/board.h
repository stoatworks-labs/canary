/*
 * CANary rev A board pin map.
 *
 * SINGLE SOURCE OF TRUTH for anything that touches a pin. Every value here was
 * extracted from hardware/canary.kicad_pcb (net -> U301 module pad) and then
 * translated pad -> GPIO using the ESP32-S3-WROOM-1 symbol in KiCad's
 * RF_Module library, rather than from anyone's memory of the module pinout.
 *
 *   net          U301 pad   symbol pin   GPIO
 *   CAN_TX          4         IO4          4
 *   CAN_RX          5         IO5          5
 *   LED_LAN         8         IO15        15
 *   LED_ERR         9         IO16        16
 *   LED_CAN        10         IO17        17
 *   PD_PG          11         IO18        18
 *   USB_DM         13         USB_D-      19  (native USB, not GPIO-driven)
 *   USB_DP         14         USB_D+      20  (native USB, not GPIO-driven)
 *   ETH_RSTn       17         IO9          9
 *   ETH_CSn        18         IO10        10
 *   SPI_MOSI       19         IO11        11
 *   SPI_SCK        20         IO12        12
 *   SPI_MISO       21         IO13        13
 *   ETH_INTn       22         IO14        14
 *   BOOT           27         IO0          0
 *   UART0_RXD      36         RXD0        44
 *   UART0_TXD      37         TXD0        43
 *
 * The board has NO 3V3 LED under MCU control: D304 "ON" is wired from VCC_3V3
 * through R305, so it lights whenever the rail is up. Only the three below are
 * firmware-driven, and all three are ACTIVE HIGH.
 *
 * LED POLARITY - corrected 2026-07-27, read this before "fixing" it back.
 * This was ACTIVE LOW here until the bring-up work re-derived it from the
 * board file, and the old comment described the connection backwards. What
 * the board actually says:
 *
 *   KiCad's Device:LED symbol is pin 1 = K (cathode), pin 2 = A (anode).
 *   D301.1 -> GND,  D301.2 -> R302 -> GPIO15.       (same shape for D302/D303)
 *   D304.1 -> GND,  D304.2 -> R305 -> VCC_3V3.
 *
 * D304 settles it. It has no GPIO: it is a rail-powered ON lamp and it MUST
 * light whenever 3V3 is up. That only works if current flows R305 -> pin 2 ->
 * pin 1 -> GND, so pin 2 is the anode. D301-D303 have the identical topology
 * with a GPIO where D304 has the rail, so driving the GPIO HIGH lights them.
 *
 * The net names LED_LAN_K / LED_ERR_K / LED_CAN_K / LED_ON_K are therefore
 * misnamed - those nodes are the ANODE side. Renaming them is on the rev B
 * list; the names are cosmetic, the polarity is not.
 *
 * NOT YET CONFIRMED ON HARDWARE. hardware/fab/test/BENCH-BRINGUP.md step 6.3
 * is the check: if all three LEDs come up inverted, this constant is wrong and
 * the schematic reading above is wrong with it.
 */
#ifndef BOARD_H
#define BOARD_H

/* ---- Ethernet: W5500 on SPI2 (FSPI) ------------------------------------- */
#define BOARD_ETH_SPI_HOST      SPI2_HOST
#define BOARD_ETH_SCK_GPIO      12
#define BOARD_ETH_MOSI_GPIO     11
#define BOARD_ETH_MISO_GPIO     13
#define BOARD_ETH_CS_GPIO       10
#define BOARD_ETH_INT_GPIO      14
#define BOARD_ETH_RST_GPIO       9

/* W5500 tolerates up to 80 MHz but the datasheet's guaranteed figure is
 * 33.3 MHz; 20 MHz is the value Espressif's own example uses and leaves
 * margin for this board's un-length-matched SPI routing. */
#define BOARD_ETH_SPI_CLOCK_MHZ 20

/* ---- Isolated CAN: ADM3053 ---------------------------------------------- */
#define BOARD_CAN_TX_GPIO        4
#define BOARD_CAN_RX_GPIO        5

/* ---- Status LEDs (ACTIVE HIGH - see header comment) --------------------- */
#define BOARD_LED_LAN_GPIO      15
#define BOARD_LED_ERR_GPIO      16
#define BOARD_LED_CAN_GPIO      17
#define BOARD_LED_ACTIVE_LEVEL   1

/* ---- Misc --------------------------------------------------------------- */
#define BOARD_PD_PG_GPIO        18   /* CH224K power-good, input */
#define BOARD_BOOT_GPIO          0   /* SW302, also the ROM download strap */

#endif /* BOARD_H */
