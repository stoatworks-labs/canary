#!/bin/sh
# Build canaryd — the shipping bridge firmware as a host process.
#
# Same warning discipline as the component tests: -Wall -Wextra -Werror, and
# the component sources are compiled UNMODIFIED. If a component stops building
# here, it is because it grew a dependency the shim does not cover; add it to
# the shim rather than adapting the component.
#
#   ./build.sh              plain
#   SAN=1 ./build.sh        + AddressSanitizer and UndefinedBehaviorSanitizer
set -e
cd "$(dirname "$0")"

CC=${CC:-cc}
OUT=${OUT:-./canaryd}
COMPONENTS=../components

CFLAGS="-std=c99 -D_DARWIN_C_SOURCE -D_GNU_SOURCE -Wall -Wextra -Werror -O1 -g"
INCLUDES="-Ishim \
 -I$COMPONENTS/bridge/include \
 -I$COMPONENTS/rmbcp/include \
 -I$COMPONENTS/r70_ddt/include \
 -I$COMPONENTS/dbcan/include"

if [ -n "$SAN" ]; then
    CFLAGS="$CFLAGS -fsanitize=address,undefined -fno-omit-frame-pointer"
fi

# shellcheck disable=SC2086
"$CC" $CFLAGS $INCLUDES \
    "$COMPONENTS/bridge/bridge.c" \
    "$COMPONENTS/rmbcp/rmbcp.c" \
    "$COMPONENTS/r70_ddt/r70_ddt.c" \
    "$COMPONENTS/dbcan/dbcan.c" \
    runtime.c vcan.c host_main.c \
    -lpthread -o "$OUT"

echo "built $OUT"
