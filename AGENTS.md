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
- Source is MIT by default under root `LICENSE`. The complete
  `map-checker-qt/` subtree remains GPL-2.0-or-later under its own `LICENSE`,
  including generated PyQt files, tests, configuration, launchers, and docs.
  Never move or copy material across that boundary without a complete
  provenance and license review. Preserve the separate PyQt5 and downloaded
  content-catalog dependency terms.
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
