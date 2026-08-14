# Contributing

Use a Conventional Commits pull-request title and run the validation commands
for each changed utility. Keep component-specific build tooling in its owning
repository, consume the released protocol package for packet-aware Python
tools, and keep autonomous gameplay testing in the independent
[`atrinik/playtester`](https://github.com/atrinik/playtester) repository.

Contributions are MIT by default under root `LICENSE`. The complete
`map-checker-qt/` subtree is the sole GPL-2.0-or-later exception under
`map-checker-qt/LICENSE`; preserve that scope for its source, generated PyQt
files, tests, configuration, launchers, and documentation. Do not move material
across that boundary without a complete provenance and license review. Keep
PyQt5 and downloaded catalog dependencies under their own terms, and update
`PROVENANCE.md` whenever the current-tree rights basis or dependency boundary
changes.
