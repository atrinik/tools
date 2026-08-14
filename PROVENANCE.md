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
  `atrinik/atrinik@3c21ce575076be9effee102b5e95b52399bfceed`.

The audit used the complete local object graph with replace objects disabled,
followed path history across renames and moves, compared every retained path to
the baseline tree, and reviewed contributor, generated-file, dependency, and
embedded-notice boundaries. No confidential identity mapping or restricted
evidence was copied into this repository.

The current maintainer and issue author, Zoey Rose (`github:zoeyrose`), attests
through issue #22, root `LICENSE`, and pull request #23 that she personally
authored, or commissioned and directed as agent-assisted work, every admitted
human-authored contribution listed below; that she owns the rights needed to
license those contributions; and that she licenses them under MIT. This is the
explicit contemporaneous rights grant for both pre-transition and transition
work. It is not inferred from Git names, email addresses, or tool use. No former
identity is inferred or published. Pull request #23 is the public
implementation, attestation, and review record; its final head and tree are the
destination coordinates because a commit cannot contain its own hash.

The historical diagnostic implementations were not relicensed. Their baseline
blobs remain GPL in history. The current implementations were authored under
the contemporaneous grant above. Blank lines, standard language scaffolding,
and the GNU tool invocation sequence dictated by the retained functional
contract are separately classified as non-copyrightable; their exact historical
commits are recorded below rather than hidden by a re-authorship claim. The
mechanical Dependabot version-coordinate substitution is separately classified
below and contributes no retained expressive implementation requiring a grant. Consequently no
historical identity attestation is used to place a file in the MIT-default
scope; any unresolved historical identity remains fail-closed and historical
only.

## Contribution ledger

The commit lists are the complete current-tree line-provenance sets from
`git blame --line-porcelain HEAD -- <path>`, after following each path's complete
history, with the final manifest-only commit represented by pull request #23's
destination head/tree. All listed expressive contributions except the
separately identified Dependabot and diagnostic-contract fragments were
authored under the explicit contemporaneous grant above.

| Current path | Exact admitted source contributions | Classification, transformation, and review |
| --- | --- | --- |
| `.gitignore` | `a6904f87ec9cc02294abf2293e4d1e462653dece`, `56fa28993ef2bbf38815074a14c5f4b6fe9a137e`, `68a9d457f19c608b2e848c7de1496b7154af7633` | Current-public-identity work; retained as MIT metadata and reviewed by `github:zoeyrose` |
| `.github/dependabot.yml` | `843a3dff3a36135a9a60aff7c6a3fcc762f704d3` | Current-public-identity work; retained as MIT dependency policy and reviewed by `github:zoeyrose` |
| `.github/workflows/check.yml` | `a6904f87ec9cc02294abf2293e4d1e462653dece`, `25dbbbc00d8bbeb98c7d0f73cdf56145b517c398`, `55d2ce6f8d09a52d3ce4b25447d187900213179c`, `56fa28993ef2bbf38815074a14c5f4b6fe9a137e`, transition commit `124c2793a27bd9746d3ecdcb85c81664e9abe58a` | Current-public-identity workflow expression; retired steps removed and MIT tests added; reviewed by `github:zoeyrose` |
| `.github/workflows/pr-title.yml` | `a6904f87ec9cc02294abf2293e4d1e462653dece` | Current-public-identity work; retained as MIT policy and reviewed by `github:zoeyrose` |
| `.github/workflows/release.yml` | `77b39021353a4aec36632001d232f085d5b65667`, `68bf7139c98b1d6d88ee2a3f475a20cbeaee989e`, `25dbbbc00d8bbeb98c7d0f73cdf56145b517c398`, `6dfd98d630c6194b1545d95e55a5ca69d903129a`, `a90cfb5b92c1c6cc4f55a0d92949593457be604e` | Current-public-identity workflow expression; retained under contemporaneous MIT authorization and reviewed by `github:zoeyrose` |
| `.github/workflows/check.yml`, `.github/workflows/release.yml` | Dependabot commit `80f14561b9090b1573a89feaf75053a490a891bc` | Separately classified non-copyrightable mechanical substitution of the factual immutable `actions/checkout` version/commit coordinate; no bot-authored expression or grant presumed |
| `.releaserc.json` | `77b39021353a4aec36632001d232f085d5b65667`, `25dbbbc00d8bbeb98c7d0f73cdf56145b517c398`, `49df09157f1bc701bc5a48ae2e21c5b48dbc65cc`, `7d95669c6756219779907811386d64c2492ddc46` | Current-public-identity release configuration; contemporaneously authorized under MIT and reviewed by `github:zoeyrose` |
| `AGENTS.md` | `68a9d457f19c608b2e848c7de1496b7154af7633`, `75bf3a2304cc9ac7f03efe4f2f3c9f6bbb11acad`, transition commit `124c2793a27bd9746d3ecdcb85c81664e9abe58a` | Current-public-identity documentation, rewritten for the mixed boundary and reviewed by `github:zoeyrose` |
| `CONTRIBUTING.md` | `8469be5cfa3a3ef207607fec87fa609c8d585d7c`, `75bf3a2304cc9ac7f03efe4f2f3c9f6bbb11acad`, transition commit `124c2793a27bd9746d3ecdcb85c81664e9abe58a` | Current-public-identity documentation, rewritten for default/exception contribution scopes and reviewed by `github:zoeyrose` |
| `README.md` | `a6904f87ec9cc02294abf2293e4d1e462653dece`, `b0f27045a0491fd9d3f36d8ac63159c713a6c601`, `75bf3a2304cc9ac7f03efe4f2f3c9f6bbb11acad`, `56fa28993ef2bbf38815074a14c5f4b6fe9a137e`, `55d2ce6f8d09a52d3ce4b25447d187900213179c`, `72f0bf821fb149ed4d2212cae520de6644db44b6`, transition commits `3ce48bfa62edfea491304a5424da71ff2c6b79c3`, `124c2793a27bd9746d3ecdcb85c81664e9abe58a`, `4d9184dc9b052e0dca44db273b895e89874f1b93` | Current-public-identity documentation; retired paths removed and license boundary rewritten; reviewed by `github:zoeyrose` |

Transition-created MIT-default paths are inventoried separately because they
have no baseline contribution set:

| Current path | Exact admitted source contributions | Classification, transformation, and review |
| --- | --- | --- |
| `LICENSE` | `124c2793a27bd9746d3ecdcb85c81664e9abe58a`; final wording in pull request #23 destination | Standard MIT text and Zoey Rose copyright notice; reviewed by `github:zoeyrose` |
| `PROVENANCE.md` | `124c2793a27bd9746d3ecdcb85c81664e9abe58a`, `4d9184dc9b052e0dca44db273b895e89874f1b93`; final manifest-only change in pull request #23 destination | Agent-assisted record commissioned, directed, owned, granted, and reviewed by `github:zoeyrose` |
| `split_symbols.sh` | `124c2793a27bd9746d3ecdcb85c81664e9abe58a`, `a41ffca9ea5bc737039e66b9ed51cb235a2523c1`; historical non-expressive fragments classified below | Agent-assisted expressive implementation commissioned, directed, owned, granted, and reviewed by `github:zoeyrose`; retained functional GNU-tool sequence separately non-copyrightable |
| `stacktrace.py` | `124c2793a27bd9746d3ecdcb85c81664e9abe58a`, `a41ffca9ea5bc737039e66b9ed51cb235a2523c1`; historical non-expressive fragments classified below | Agent-assisted expressive implementation commissioned, directed, owned, granted, and reviewed by `github:zoeyrose`; standard syntax/scaffolding separately non-copyrightable |
| `tests/__init__.py` | `124c2793a27bd9746d3ecdcb85c81664e9abe58a` | Empty package marker; non-expressive metadata |
| `tests/test_diagnostics.py` | `124c2793a27bd9746d3ecdcb85c81664e9abe58a`, `4d9184dc9b052e0dca44db273b895e89874f1b93`, `a41ffca9ea5bc737039e66b9ed51cb235a2523c1` | Agent-assisted test expression commissioned, directed, owned, granted, and reviewed by `github:zoeyrose` |

The historic `split_symbols.sh` baseline blob
`ce6030376eb25ddc9cd1566603d3448e6071c613` and `stacktrace.py` baseline blob
`fa78cc708dd750628f6ae530e912ee657aa8d97e` are explicitly excluded. Commit
`124c2793a27bd9746d3ecdcb85c81664e9abe58a` replaced their expressive
implementations; `a41ffca9ea5bc737039e66b9ed51cb235a2523c1` completed compatibility and
transactional failure behavior. Current `git blame` also names historical
commits `cd12a49557cb5b89a8b708fed1f3ca2510465786`,
`400b50e0ce9e49c493abf4405fc31aebd175970f`, and
`d5ea8b9856fd8a17bdb263ef5a51759acba4e83a` solely for blank lines, braces,
standard module/entry-point scaffolding, `print`/`continue`, and the functional
GNU `objcopy` → `strip` → `objcopy --add-gnu-debuglink` → `chmod` contract.
Those minimal fragments and required operation ordering are classified as
non-copyrightable facts, methods of operation, or standard syntax—not as
relicensed historical expression. Reviewer `github:zoeyrose` confirmed that
classification and granted the new expressive implementations under MIT.

## Per-file inventory

| Current path | Classification and rights basis | Transformation / review |
| --- | --- | --- |
| `LICENSE` | Standard MIT license text | New default license; not project implementation |
| `.gitignore` | Contribution ledger above | Reviewed for generated and mutable paths |
| `.github/dependabot.yml` | Contribution ledger above | Dependency-update schedule; no vendored material |
| `.github/workflows/check.yml` | Contribution ledger above | Retained validation only; immutable Action pin |
| `.github/workflows/pr-title.yml` | Contribution ledger above | Conventional-title policy; immutable Action-free workflow |
| `.github/workflows/release.yml` | Contribution ledger above | Semantic-release policy; immutable Action pins |
| `.releaserc.json` | Contribution ledger above | Semantic-release configuration |
| `AGENTS.md` | Contribution ledger above | Rewritten for the mixed-license live tree |
| `CONTRIBUTING.md` | Contribution ledger above | Rewritten for default and exception scopes |
| `README.md` | Contribution ledger above | Rewritten for retained tools and license disclosure |
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
