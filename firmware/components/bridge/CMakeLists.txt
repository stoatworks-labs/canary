idf_component_register(
    SRCS "bridge.c"
    INCLUDE_DIRS "include"
    REQUIRES rmbcp r70_ddt dbcan net lwip esp_netif
)
