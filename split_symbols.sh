#!/usr/bin/env bash

set -euo pipefail

usage() {
    printf 'Usage: %s <executable>\n' "${0##*/}"
}

if (( $# < 1 )); then
    usage
    exit 0
fi

target=$1
target_dir=$(dirname -- "${target}")
target_name=$(basename -- "${target}")
debug_name="${target_name}.debug"

cd -- "${target_dir}"

if [[ -L "${target_name}" || ! -f "${target_name}" ]]; then
    printf 'Not a regular file: %s\n' "${target}"
    exit 1
fi
if [[ -L "${debug_name}" || ( -e "${debug_name}" && ! -f "${debug_name}" ) ]]; then
    printf 'Refusing non-regular debug destination: %s\n' "${target_dir}/${debug_name}" >&2
    exit 1
fi

scratch=$(mktemp -d ".split-symbols.XXXXXXXX")
cleanup() {
    rm -rf -- "${scratch}"
}
trap cleanup EXIT

cp -p -- "${target_name}" "${scratch}/${target_name}"

printf 'Stripping %s; writing debug information to %s\n' \
    "${target_name}" "${debug_name}"
objcopy --only-keep-debug -- "${target_name}" "${scratch}/${debug_name}"
strip --strip-debug --strip-unneeded -- "${scratch}/${target_name}"
(
    cd -- "${scratch}"
    objcopy --add-gnu-debuglink="${debug_name}" -- "${target_name}"
)
chmod a-x -- "${scratch}/${debug_name}"
mv -T -- "${scratch}/${debug_name}" "${debug_name}"
mv -T -- "${scratch}/${target_name}" "${target_name}"
