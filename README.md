# Atrinik tools

This repository contains the retained standalone utilities used to inspect and
diagnose Atrinik data and binaries. Component build tools live with the
component they operate on:

- content collection and validation: shared
  [`atrinik/content@main`](https://github.com/atrinik/content); retained `1.x`
  revisions are historical release and migration evidence only
- client dependency and packaging tools: replacement
  [`atrinik/client`](https://github.com/atrinik/client), maintained Classic
  [`atrinik/classic/client`](https://github.com/atrinik/classic/tree/main/client)
- server dependency, runtime, and packaging tools: replacement
  [`atrinik/server`](https://github.com/atrinik/server), maintained Classic
  [`atrinik/classic/server`](https://github.com/atrinik/classic/tree/main/server)

## Included utilities

- `map-checker-qt/`: checksum-pinned map inspection application
- `split_symbols.sh` and `stacktrace.py`: native binary diagnostics

Read the Qt checker documentation before using it against a working content
checkout.

The former `atrinik_bot/` utility is now maintained independently as
[`atrinik/playtester`](https://github.com/atrinik/playtester).

The Qt map checker consumes the checksum-pinned content catalog before every
focused scan. See [`map-checker-qt/README.md`](map-checker-qt/README.md) for
dependency setup, GUI configuration, and headless validation commands.

## Protocol consumers

Python tools that exchange or decode game packets must depend on a pinned
compatible protocol binding rather than copying command identifiers or packet
definitions into this repository. New compatible consumers should use releases
from the replacement [`atrinik/protocol`](https://github.com/atrinik/protocol)
repository. Keeping the dependency explicit lets applications share canonical
generated bindings for the protocol generation they implement.

## License

This repository is MIT by default under the root [LICENSE](LICENSE), with one
directory exception: the complete `map-checker-qt/` subtree remains
GPL-2.0-or-later under [its own license](map-checker-qt/LICENSE). That exception
includes the checker's source, tests, configuration, `.ui` files, generated
`ui_*.py` files, launchers, and documentation. The current source archive is
therefore not MIT-only.

PyQt5 and the checksum-pinned downloaded content catalog retain their separate
dependency and distribution terms and are not relicensed by either repository
license. See [PROVENANCE.md](PROVENANCE.md) for the current-tree audit and the
historical release boundary. Tags and releases `v1.0.0` through `v1.2.6`
remain described by the GPL terms that applied when they were published.
