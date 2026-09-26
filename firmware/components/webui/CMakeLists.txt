# www/index.html is embedded in the binary rather than served from a filesystem
# partition: it is one small self-contained file, and a SPIFFS/FAT partition
# would mean changing the partition table, which changes OTA compatibility.
idf_component_register(
    SRCS "webui.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_http_server json config diag net usbnet bridge dbcan app_update esp_timer
    EMBED_FILES "www/index.html"
)
