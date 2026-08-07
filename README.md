# Atrinik tools

This repository contains the committed standalone utilities used to inspect,
author, package, and diagnose Atrinik data and binaries. Component build tools
live with the component they operate on:

- content collection and validation: [`atrinik/content`](https://github.com/atrinik/content)
- client dependency and packaging tools: [`atrinik/client`](https://github.com/atrinik/client)
- server dependency, runtime, and packaging tools: [`atrinik/server`](https://github.com/atrinik/server)

## Included utilities

- `gridarta-types-convert/` and `gridarta_materials.pl`: editor data conversion
- `map-checker/` and `map-checker-qt/`: map inspection applications
- `map-maker/`: map-maker package assembly
- `mapset/`: operations over sets of maps
- `randomizer/`: archetype variation utility
- `worldviewer/`: browser-based world viewer
- `atrinik_bot/`: headless client and automation engine using the shared native
  pathfinding core and released protocol bindings
- `split_symbols.sh` and `stacktrace.py`: native binary diagnostics

Some utilities retain their original runtime and dependency requirements. Read
the documentation beside a utility before using it against a working content
checkout.

The Qt map checker consumes the checksum-pinned content catalog before every
focused scan. See [`map-checker-qt/README.md`](map-checker-qt/README.md) for
dependency setup, GUI configuration, and headless validation commands.

## Protocol consumers

Python tools that exchange or decode game packets must depend on a pinned
release of the
[`atrinik-protocol`](https://github.com/atrinik/protocol) Python package. New
tools must not copy command identifiers or packet definitions into this
repository. Keeping the protocol dependency explicit lets applications,
including `atrinik_bot`, share the canonical generated bindings.

## License

The extracted source retains its existing GNU General Public License terms.
See [COPYING](COPYING).
