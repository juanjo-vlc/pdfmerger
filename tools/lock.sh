#!/bin/bash
# Regenerate the hashed lock files used for release builds (needs `uv`).
#   tools/lock.sh            # keep current pins where possible
#   tools/lock.sh --upgrade  # move everything to the latest allowed versions
set -euo pipefail
cd "$(dirname "$0")/.."
common=(--generate-hashes --python-platform x86_64-pc-windows-msvc
        --override requirements/overrides.txt --no-header --quiet "$@")
uv pip compile requirements/windows.in --python-version 3.12 \
    -o requirements/windows-py312.lock "${common[@]}"
uv pip compile packaging/docker/requirements-build.in --python-version 3.13 \
    -o packaging/docker/requirements-build.lock "${common[@]}"
uv pip compile tools/fuzz/requirements.in --python-version 3.12 \
    --python-platform x86_64-manylinux_2_28 --generate-hashes \
    --override requirements/overrides.txt --no-header --quiet "$@" \
    -o tools/fuzz/requirements.lock
echo "Locks updated. Review the diff before committing."
