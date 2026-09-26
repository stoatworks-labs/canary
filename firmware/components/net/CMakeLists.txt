idf_component_register(
    SRCS "net.c" "net_select.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_wifi esp_netif esp_event esp_eth driver lwip board
)
