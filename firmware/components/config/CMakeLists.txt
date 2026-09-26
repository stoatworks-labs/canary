# config_check.c is ESP-IDF-free and host-tested (test/run_tests.sh); it is
# compiled into the component here as well so there is exactly one copy of the
# rules the firmware and the tests both use.
idf_component_register(
    SRCS "config_check.c" "config_store.c"
    INCLUDE_DIRS "include" "."
    REQUIRES nvs_flash r70_ddt
)
