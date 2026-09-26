# The esp_tinyusb dependency is declared in idf_component.yml and is pulled
# from the component registry on first build. It is fetched whatever the build
# configuration, but nothing links unless CONFIG_TINYUSB_NET_MODE_NCM is set:
# without it usbnet.c compiles to the stub at the top of the file.
idf_component_register(
    SRCS "usbnet.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_netif esp_event esp_hw_support lwip
)
