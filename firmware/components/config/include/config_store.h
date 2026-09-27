/*
 * Persistent settings: storage.
 *
 * The shape of the settings and what makes one unusable is config_check.h,
 * which is ESP-IDF-free and host-tested. This half is the NVS.
 *
 * Reading is cheap and happens once at boot. Writing is rare and takes effect
 * at the NEXT boot: net.c hands its address to lwip during bring-up and the
 * bridge copies its config when it starts, so changing either underneath them
 * would leave half the system on the old value. Saying "reboot to apply" is
 * honest and is what a converter should do; quietly applying half of it is not.
 */
#ifndef CONFIG_STORE_H
#define CONFIG_STORE_H

#include "config_check.h"
#include "esp_err.h"

/* Load from NVS, filling anything unset from cfg_defaults().
 *
 * NEVER FAILS INTO AN UNUSABLE STATE: a missing namespace, a partial write, a
 * key of the wrong type or a stored value that no longer validates all yield
 * the defaults, because a converter that will not boot because its own
 * settings are corrupt is worse than one on factory settings. Anything
 * replaced is logged. */
esp_err_t cfg_load(cfg_t *out);

/* Validate and store. Returns ESP_ERR_INVALID_ARG if cfg_validate() objects,
 * without writing anything. Takes effect at the next boot. */
esp_err_t cfg_save(const cfg_t *cfg);

/* Erase the whole namespace, so the next boot is on defaults. */
esp_err_t cfg_reset(void);

/* True if the settings in use came from NVS rather than from cfg_defaults().
 * The web UI says so, because "why is it called CANary again" is otherwise a
 * long conversation. */
bool cfg_is_stored(void);

#endif /* CONFIG_STORE_H */
