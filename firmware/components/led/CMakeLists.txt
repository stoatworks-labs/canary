idf_component_register(
    SRCS "led.c" "led_patterns.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "."
    REQUIRES driver board
)
