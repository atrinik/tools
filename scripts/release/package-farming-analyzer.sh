#!/usr/bin/env bash
# Package the MIT farming analyzer as a deterministic release asset so
# consumers can pin it by digest instead of a mutable source archive.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 TAG OUTPUT_DIRECTORY" >&2
  exit 2
fi

tag=$1
output_directory=$2
if [[ ! ${tag} =~ ^v([0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
  echo "invalid release tag: ${tag}" >&2
  exit 1
fi

version=${BASH_REMATCH[1]}
source_commit=$(git rev-parse "${tag}^{commit}")
if ! git merge-base --is-ancestor "${source_commit}" refs/heads/main &&
  ! git merge-base --is-ancestor "${source_commit}" refs/remotes/origin/main; then
  echo "release tag is not reachable from main: ${tag}" >&2
  exit 1
fi

package=atrinik-tools-farming-analyzer-${version}
mkdir -p "${output_directory}"
# git archive records the commit time for every member; gzip -n omits the
# name and timestamp, so the same tag always yields the same bytes.
git archive --format=tar --prefix="${package}/" "${source_commit}" LICENSE farming_analyzer |
  gzip -9n >"${output_directory}/${package}.tar.gz"
(
  cd "${output_directory}"
  sha256sum "${package}.tar.gz" >SHA256SUMS
)
