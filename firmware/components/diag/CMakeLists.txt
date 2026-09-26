idf_component_register(
    SRCS "diag.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_app_format espcoredump nvs_flash esp_partition esp_timer json
    PRIV_REQUIRES spi_flash esp_hw_support
)
