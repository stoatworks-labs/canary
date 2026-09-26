idf_component_register(
    SRCS "app_main.c" "status.c"
    INCLUDE_DIRS "."
    REQUIRES diag bridge net usbnet webui config board led dbcan selftest nvs_flash esp_event esp_hw_support app_update
)

# `idf.py build -DDBCANARY_SELFTEST=1` builds the bench test image instead of
# the product. Same plumbing as DBCANARY_USE_WIFI below: idf.py's -D only sets
# a CMake variable, so it has to be forwarded to the compiler explicitly or the
# build silently stays on the product path.
if(DBCANARY_SELFTEST)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE DBCANARY_SELFTEST=1)
endif()

# Plumb the devkit Wi-Fi options from CMake cache variables through to C
# preprocessor defines, so `idf.py build -DDBCANARY_USE_WIFI=1 ...` actually
# does something. Without this, idf.py's -D only sets a CMake variable that
# nothing reads, and the build silently stays on the Ethernet path.
#
# The rev A board has no Wi-Fi in its signal path; this is for exercising the
# bridge on a plain ESP32-S3 devkit before boards exist.
if(DBCANARY_USE_WIFI)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE DBCANARY_USE_WIFI=1)
    if(DBCANARY_WIFI_SSID)
        target_compile_definitions(${COMPONENT_LIB} PRIVATE
            DBCANARY_WIFI_SSID="${DBCANARY_WIFI_SSID}")
    endif()
    if(DBCANARY_WIFI_PASS)
        target_compile_definitions(${COMPONENT_LIB} PRIVATE
            DBCANARY_WIFI_PASS="${DBCANARY_WIFI_PASS}")
    endif()
endif()
