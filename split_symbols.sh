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

cp --preserve=all -- "${target_name}" "${scratch}/original"
cp --preserve=all -- "${target_name}" "${scratch}/${target_name}"
had_debug=false
if [[ -f "${debug_name}" ]]; then
    cp --preserve=all -- "${debug_name}" "${scratch}/previous.debug"
    had_debug=true
fi

printf 'Stripping %s; writing debug information to %s\n' \
    "${target_name}" "${debug_name}"
objcopy --only-keep-debug -- "${target_name}" "${scratch}/${debug_name}"
strip --strip-debug --strip-unneeded -- "${scratch}/${target_name}"
(
    cd -- "${scratch}"
    objcopy --add-gnu-debuglink="${debug_name}" -- "${target_name}"
)
chmod a-x -- "${scratch}/${debug_name}"
if [[ ${had_debug} == true ]]; then
    if ! cp --preserve=mode,ownership,timestamps,xattr -- \
        "${scratch}/${debug_name}" "${debug_name}"; then
        cp --preserve=mode,ownership,timestamps,xattr -- \
            "${scratch}/previous.debug" "${debug_name}" || true
        printf 'Failed to publish debug information: %s\n' \
            "${target_dir}/${debug_name}" >&2
        exit 1
    fi
else
    mv -T -- "${scratch}/${debug_name}" "${debug_name}"
fi
if ! cp --preserve=mode,ownership,timestamps,xattr -- "${scratch}/${target_name}" "${target_name}"; then
    rollback_status=0
    cp --preserve=mode,ownership,timestamps,xattr -- "${scratch}/original" "${target_name}" || rollback_status=$?
    if [[ ${had_debug} == true ]]; then
        cp --preserve=mode,ownership,timestamps,xattr -- \
            "${scratch}/previous.debug" "${debug_name}" || rollback_status=$?
    else
        rm -f -- "${debug_name}" || rollback_status=$?
    fi
    if (( rollback_status != 0 )); then
        printf 'Failed to publish %s and rollback was incomplete\n' "${target}" >&2
        exit "${rollback_status}"
    fi
    printf 'Failed to publish stripped executable: %s\n' "${target}" >&2
    exit 1
fi
