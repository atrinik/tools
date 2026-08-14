# Current-tree provenance

This record covers the live tree introduced by the MIT-default transition. It
does not change the license of any tag, release, historical revision, or Git
object published before the transition.

## Audit coordinates and method

- Audited source repository: `atrinik/tools`.
- Complete, non-shallow baseline commit:
  `7777cf9f9ab6deb58de8a481dfccd6b05d86e3e1` (tree
  `daeb2eb5771d3f90ecf70ccfa2d9e1e4d768f6e4`).
- Historical grant-policy revision:
  `atrinik/atrinik@f0d1225791da7484e9456b39104cc30b0c77fe52`.
- Privacy-preserving identity-policy revision:
  `atrinik/atrinik@6f6040212f0fa0cb6b8e4e695d1488a403d966be`.
- Current coordinator default-branch review revision:
  `atrinik/atrinik@82ec53a0ad8657f24907fe37464d6cd4afd7d7fa`.

The audit used the complete local object graph with replace objects disabled,
followed path history across renames and moves, compared every retained path to
the baseline tree, and reviewed contributor, generated-file, dependency, and
embedded-notice boundaries. No confidential identity mapping or restricted
evidence was copied into this repository.

The historical `split_symbols.sh` and `stacktrace.py` implementations were not
relicensed. Their predecessor bytes remain GPL in history; the current files
are new implementations contributed under the root MIT license from their
small public command-line contracts. Repository policy, documentation, tests,
and automation are likewise contemporaneously adopted under MIT by the
transition. The mechanical Dependabot version-coordinate substitution in the
pre-transition workflow contributes no retained expressive implementation that
requires a historical grant. Consequently no historical identity attestation
is used to place a file in the MIT-default scope; any unresolved historical
identity remains fail-closed and historical only.

## Per-file inventory

| Current path | Classification and rights basis | Transformation / review |
| --- | --- | --- |
| `LICENSE` | Standard MIT license text | New default license; not project implementation |
| `.gitignore` | Contemporaneous MIT repository metadata | Reviewed for generated and mutable paths |
| `.github/dependabot.yml` | Contemporaneous MIT repository metadata | Dependency-update schedule; no vendored material |
| `.github/workflows/check.yml` | Contemporaneous MIT repository metadata | Retained validation only; immutable Action pin |
| `.github/workflows/pr-title.yml` | Contemporaneous MIT repository metadata | Conventional-title policy; immutable Action-free workflow |
| `.github/workflows/release.yml` | Contemporaneous MIT repository metadata | Semantic-release policy; immutable Action pins |
| `.releaserc.json` | Contemporaneous MIT repository metadata | Semantic-release configuration |
| `AGENTS.md` | Contemporaneous MIT documentation | Rewritten for the mixed-license live tree |
| `CONTRIBUTING.md` | Contemporaneous MIT documentation | Rewritten for default and exception scopes |
| `README.md` | Contemporaneous MIT documentation | Rewritten for retained tools and license disclosure |
| `PROVENANCE.md` | Contemporaneous MIT provenance record | New complete-tree audit record |
| `split_symbols.sh` | Contemporaneous MIT reimplementation | Historical GPL bytes excluded; CLI contract preserved |
| `stacktrace.py` | Contemporaneous MIT reimplementation | Historical GPL bytes excluded; CLI contract preserved |
| `tests/__init__.py` | Contemporaneous MIT test metadata | New |
| `tests/test_diagnostics.py` | Contemporaneous MIT tests | New CLI/parser regression coverage |

Every path under `map-checker-qt/`, including source, tests, configuration,
`.ui` files, generated `ui_*.py` files, launchers, the catalog lock, README, and
the subtree `LICENSE`, is excluded from the table because it remains
GPL-2.0-or-later as one scoped unit. The complete unmodified GPLv2 text moved
from baseline root `COPYING` to `map-checker-qt/LICENSE`; both blobs have
SHA-256 `d8c320ffc0030d1b096ae4732b50d2b811cf95e9a9b7377c1127b2563e0a0388`.

## Third-party and generated boundaries

- `map-checker-qt` uses PyQt5 at runtime under PyQt's own distribution terms;
  PyQt5 is not vendored here.
- `map-checker-qt/catalog.lock.json` downloads the separately licensed
  `atrinik/content` catalog at its exact tag, commit, URL, and SHA-256. The
  downloaded package remains ignored and is not part of this repository.
- Generated `map-checker-qt/ui/ui_*.py` files remain inside the GPL subtree and
  are not presented as MIT material.
- GitHub Actions and semantic-release packages are external dependencies under
  their own terms and are consumed by immutable coordinates or exact versions,
  not vendored.

The removed converter, legacy checker, map maker, mapset, randomizer, and world
viewer—including their Crossfire, Daimonin-fork, Nicolas Weeger, and Edwin
Miltenburg contribution boundaries—remain available only in historical GPL
revisions and releases. No current tracked path outside `map-checker-qt/`
contains those implementations or notices.
