#!/usr/bin/env bash
set -euo pipefail

cd "${WORKING_DIRECTORY:-.}"

head_sha="$(git rev-parse HEAD)"
args=(--title "$TAG" --generate-notes)
if [[ "${PRERELEASE:-false}" == "true" ]]; then
  args+=(--prerelease)
fi

if git rev-parse --verify --quiet "refs/tags/$TAG" >/dev/null; then
  tag_sha="$(git rev-parse "refs/tags/$TAG^{commit}")"
  if [[ "$tag_sha" != "$head_sha" ]]; then
    echo "::error::Tag $TAG points to $tag_sha, not HEAD ($head_sha)"
    exit 1
  fi
  if gh release view "$TAG" >/dev/null 2>&1; then
    gh release upload "$TAG" "$ZIP_PATH" "$CHECKSUMS_PATH" --clobber
  else
    gh release create "$TAG" "$ZIP_PATH" "$CHECKSUMS_PATH" "${args[@]}" --verify-tag
  fi
else
  if gh release view "$TAG" >/dev/null 2>&1; then
    gh release upload "$TAG" "$ZIP_PATH" "$CHECKSUMS_PATH" --clobber
  else
    gh release create "$TAG" "$ZIP_PATH" "$CHECKSUMS_PATH" "${args[@]}" --target "$head_sha"
  fi
fi
