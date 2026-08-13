# Atrinik tools

This repository contains the committed standalone utilities used to inspect,
author, package, and diagnose Atrinik data and binaries. Component build tools
live with the component they operate on:

- content collection and validation: [`atrinik/content`](https://github.com/atrinik/content)
  (`main` for replacement, `1.x` for Classic)
- client dependency and packaging tools: replacement
  [`atrinik/client`](https://github.com/atrinik/client), maintained Classic
  [`atrinik/classic/client`](https://github.com/atrinik/classic/tree/main/client)
- server dependency, runtime, and packaging tools: replacement
  [`atrinik/server`](https://github.com/atrinik/server), maintained Classic
  [`atrinik/classic/server`](https://github.com/atrinik/classic/tree/main/server)

## Included utilities

- `gridarta-types-convert/` and `gridarta_materials.pl`: editor data conversion
- `map-checker/` and `map-checker-qt/`: map inspection applications
- `map-maker/`: map-maker package assembly
- `mapset/`: operations over sets of maps
- `randomizer/`: archetype variation utility
- `worldviewer/`: browser-based world viewer
- `split_symbols.sh` and `stacktrace.py`: native binary diagnostics

Some utilities retain their original runtime and dependency requirements. Read
the documentation beside a utility before using it against a working content
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

The extracted source retains its existing GNU General Public License terms.
See [COPYING](COPYING). Those terms are not a blanket outbound reuse ban:
under the
[canonical provenance policy](https://github.com/atrinik/atrinik/blob/main/docs/PROVENANCE.md),
an MIT destination may inspect exact, independently separable material as
source reference, copy it, migrate or port it, translate or adapt it, or
relicense it only after the canonical audit proves each selected contribution
is the applicable named grantor's original work. Each contribution must be
solely authored by that grantor and fall within the row's temporal scope.
Distinct contributions may cite different rows only when each independently
satisfies one row. Rows cannot be combined to cover jointly authored
contributions, generated output, or inseparable mixed work. Later material needs
contemporaneous compatible permission. This does not change the source license
here or approve a GPL dependency or bundle.
