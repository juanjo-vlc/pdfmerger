#!/bin/bash
# Development build of the portable Windows zip from Linux/WSL using Docker + Wine.
#   packaging/docker/build.sh              # -> dist/PDFMerger-<ver>-win64-wine-dev.zip
#   RUN_TESTS=1 packaging/docker/build.sh  # also run the test-suite with Windows Python
# Official release zips are produced by CI on real Windows, not by this script.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${IMAGE:-pdfmerger-winbuild:latest}"

docker build --build-arg BUILD_UID="$(id -u)" -t "$IMAGE" \
    -f "$ROOT/packaging/docker/Dockerfile" "$ROOT"
mkdir -p "$ROOT/dist"
docker run --rm \
    -v "$ROOT:/src:ro" \
    -v "$ROOT/dist:/out" \
    -e RUN_TESTS="${RUN_TESTS:-0}" \
    "$IMAGE"
