/*
 * On-device configuration UI.
 *
 * A small HTTP server and a single self-contained page: status, the settings
 * in components/config, a firmware upload, and the diagnostics bundle.
 *
 * IT LIVES ON THE USB LINK, AND ONLY THERE. Two separate mechanisms, because
 * this is the one part of the firmware that can change what the unit is:
 *
 *   1. The listening socket exists ONLY while a USB host is attached. No host,
 *      no server, no open port - not even one that accepts and hangs up. A
 *      unit sitting in a rack on a show network has nothing on port 80 at all.
 *   2. Every accepted connection is checked against the USB subnet in
 *      webui_open(), before a single byte is read. lwip's httpd cannot bind to
 *      one interface, so this is what makes "USB only" true rather than
 *      aspirational.
 *
 * The reasoning: dbCANary is a transparent bridge (AGENTS.md §1) and TCP 30000
 * has no authentication by design, exactly as a real R70 has none. A surface
 * that can rename the unit, move its port or replace its firmware is a
 * different risk class from one that carries CAN frames, and putting it behind
 * "you are holding the other end of the cable" is a stronger guarantee than
 * any password this project could ship and keep.
 *
 * NOT YET RUN ON HARDWARE, and it cannot be: it needs a USB host, and nothing
 * has ever enumerated this device. See docs/USB-NIC.md §7.
 */
#ifndef WEBUI_H
#define WEBUI_H

#include "esp_err.h"

/* Start watching the USB link. The server itself comes up when a host
 * attaches and goes away when it leaves; this returns as soon as the watcher
 * is running and never blocks on a host.
 *
 * ESP_ERR_NOT_SUPPORTED if the image has no USB network device, in which case
 * there is nowhere for this to live and it does nothing. */
esp_err_t webui_start(void);

#endif /* WEBUI_H */
