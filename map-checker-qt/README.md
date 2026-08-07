# Atrinik Qt map checker

The Qt map checker runs the authoritative Atrinik content identity catalog over
the complete authored repository before it scans a selected map or directory.
The catalog implementation is not copied into this repository: `catalog.lock.json`
pins the `atrinik/content` release tag, commit, source-archive URL, and SHA-256.

## Dependency setup

Install and verify the locked catalog package from this directory:

```sh
python3 dependencies.py sync
python3 dependencies.py verify
```

The installer accepts only the `tools/content_catalog` Python package from the
locked archive, rejects links, special files, duplicate paths, traversal, size
limit violations, and digest mismatches, and installs into ignored
`.dependencies/`. The checker refuses to scan if the dependency is absent,
modified, or does not match the lock.

## Headless validation

Validate identities across a complete `atrinik/content` checkout without a
focused legacy scan:

```sh
python3 map-checker.py --cli --catalog-only \
  --content-root /path/to/content
```

Diagnostics use the form `path:line:column: severity code: message`. The command
returns status 1 when catalog validation or dependency verification fails and 0
when the catalog is valid.

For a normal focused scan, provide the authored content root plus the collected
definition and map paths expected by the legacy checker:

```sh
python3 map-checker.py --cli \
  --content-root /path/to/content \
  --arch /path/to/runtime/lib \
  --regions /path/to/runtime/maps/regions.reg \
  --directory /path/to/runtime/maps
```

The repository-wide identity catalog always runs first, including when
`--map` or `--directory` narrows the focused scan. In the GUI, set
`path_dir_content` in `~/.map_checker.cfg`; catalog diagnostics appear in the
resource results with their source path, line, column, severity, code, and
message.

## Tests

From the tools repository root:

```sh
python3 -m unittest discover -s map-checker-qt/tests -v
python3 -W error -m compileall -q -f map-checker-qt
```
