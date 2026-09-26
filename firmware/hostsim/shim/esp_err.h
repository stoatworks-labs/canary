/*
 * ESP-IDF esp_err.h stand-in for the host build. See hostsim/README.md.
 *
 * Only the surface the bridge and dbcan components actually touch.
 */
#ifndef HOSTSIM_ESP_ERR_H
#define HOSTSIM_ESP_ERR_H

#include <stdint.h>

typedef int esp_err_t;

#define ESP_OK              0
#define ESP_FAIL           -1
#define ESP_ERR_NO_MEM      0x101
#define ESP_ERR_INVALID_ARG 0x102
#define ESP_ERR_INVALID_STATE 0x103
#define ESP_ERR_TIMEOUT     0x107
#define ESP_ERR_NOT_FOUND   0x105

const char *esp_err_to_name(esp_err_t code);

#endif /* HOSTSIM_ESP_ERR_H */
