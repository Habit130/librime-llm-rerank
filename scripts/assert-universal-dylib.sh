#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <dylib>" >&2
  exit 2
fi

file="$1"
if [[ ! -f "$file" ]]; then
  echo "missing file: ${file}" >&2
  exit 1
fi

lipo -info "${file}"
archs="$(lipo -archs "${file}")"
echo "lipo -archs: ${archs}"

missing=0
for need in arm64 x86_64; do
  found=0
  # shellcheck disable=SC2086
  for arch in ${archs}; do
    if [[ "${arch}" == "${need}" ]]; then
      found=1
      break
    fi
  done
  if [[ "${found}" -ne 1 ]]; then
    echo "missing architecture: ${need}" >&2
    missing=1
  fi
done

if [[ "${missing}" -ne 0 ]]; then
  echo "not a universal arm64+x86_64 artifact: ${file}" >&2
  exit 1
fi
