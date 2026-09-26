idf_component_register(
    SRCS "selftest.c" "selftest_report.c" "selftest_console.c"
    INCLUDE_DIRS "include"
    # The REPL lives in the `console` component; `esp_console` is the header
    # name, not a component name, and asking for it fails to resolve.
    REQUIRES board driver console esp_hw_support esp_system spi_flash
)
