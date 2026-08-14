#!/usr/bin/env bash

set -euo pipefail

usage() {
    printf 'Usage: %s <executable>\n' "${0##*/}"
}

if (( $# != 1 )); then
    usage
    exit 0
fi

target=$1
target_dir=$(dirname -- "${target}")
target_name=$(basename -- "${target}")
debug_name="${target_name}.debug"

cd -- "${target_dir}"

printf 'Stripping %s; writing debug information to %s\n' \
    "${target_name}" "${debug_name}"
objcopy --only-keep-debug -- "${target_name}" "${debug_name}"
strip --strip-debug --strip-unneeded -- "${target_name}"
objcopy --add-gnu-debuglink="${debug_name}" -- "${target_name}"
chmod a-x -- "${debug_name}"
