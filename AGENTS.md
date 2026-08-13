# Atrinik tools repository guide

- This repository owns standalone operator and content-inspection applications.
  Do not copy game/client/server implementation or make this repository the
  source of truth for content identities or wire protocols.
- The Qt map checker must consume the immutable checksum-pinned
  `content/tools/content_catalog` package described by
  `map-checker-qt/catalog.lock.json`. Never vendor an edited catalog copy.
- Dependency sync and verification are atomic trust-boundary operations: retain
  HTTPS, checksum, archive-prefix, path-traversal, link, size, metadata, and
  import-origin checks.
- Run the catalog before focused scans and convert catalog failures into
  location-aware diagnostics. Do not silently fall back to an unpinned package
  already present on `sys.path`.
- Treat GUI and CLI execution as two interfaces to the same validation logic.
  Keep headless exit statuses stable and avoid requiring a display for tests.
- New Python work must document its supported runtime and dependencies. Do not
  duplicate client/server command IDs in packet-aware tools; consume a released
  protocol binding when such tooling becomes maintained here.
- Source in this repository remains GPL as distributed under `COPYING`. That
  is not a blanket outbound reuse ban. Under the
  [canonical provenance policy](https://github.com/atrinik/atrinik/blob/main/docs/PROVENANCE.md),
  an MIT destination may inspect exact, independently separable material as
  source reference, copy it, migrate or port it, translate or adapt it, or
  relicense it only after a complete audit proves each selected contribution
  is the applicable named grantor's original work. Each contribution must be
  solely authored by that grantor and fall within the row's temporal scope.
  Distinct contributions may cite different rows only when each independently
  satisfies one row. Rows cannot be combined to cover jointly authored
  contributions, generated output, or inseparable mixed work. Later material
  needs contemporaneous compatible permission. The grants authorize only
  proven destination use. They neither change this repository's source license
  nor by themselves approve a GPL dependency, linked or combined binary,
  bundle, or surrounding material.
- Autonomous gameplay testing belongs in the independent
  [`atrinik/playtester`](https://github.com/atrinik/playtester) repository; do
  not add bot implementation or mutable bot state here.
- Validate map-checker changes with its dependency unit tests, catalog tests,
  application tests, `python3 -W error -m compileall -q -f map-checker-qt`, and
  a checksum-pinned catalog-only scan of a content checkout.
- Commits and pull-request titles use Conventional Commits. Every squash merge
  is released by semantic-release.
- Keep caches, databases, logs, downloaded dependencies, credentials, and other
  mutable runtime state untracked. Preserve unrelated work and finish with
  `git diff --check`.
- Update this `AGENTS.md` in the same change when major rework alters tool
  ownership, layout, dependency trust boundaries, interfaces, or validation.
