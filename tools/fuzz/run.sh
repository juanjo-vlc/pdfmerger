#!/bin/bash
# Fuzz the worker's PDF handling with Atheris/libFuzzer inside Docker.
#   tools/fuzz/run.sh [SECONDS]        # default 600; corpus and findings in .fuzz/
#   tools/fuzz/run.sh repro FILE       # re-run one input (e.g. a crash-* file)
# Exit code is non-zero when a finding was written to .fuzz/artifacts/.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${IMAGE:-pdfmerger-fuzz:latest}"
STATE="$ROOT/.fuzz"
mkdir -p "$STATE/corpus" "$STATE/seeds" "$STATE/artifacts"

docker build -q --build-arg FUZZ_UID="$(id -u)" -t "$IMAGE" -f "$ROOT/tools/fuzz/Dockerfile" "$ROOT" >/dev/null
run() {
    docker run --rm --network none --memory 4g --pids-limit 256 \
        -v "$ROOT:/src:ro" -v "$STATE:/work" "$@"
}

if [[ "${1:-}" == "repro" ]]; then
    f="$(realpath "$2")"
    run -v "$f:/input:ro" "$IMAGE" -runs=1 /input
    exit
fi

if [[ -z "$(ls -A "$STATE/seeds")" ]]; then
    run --entrypoint python "$IMAGE" /src/tools/fuzz/make_seeds.py /work/seeds
fi

SECONDS_TO_RUN="${1:-600}"
set +e
run "$IMAGE" -max_total_time="$SECONDS_TO_RUN" -timeout=20 -rss_limit_mb=3072 \
    -max_len=262144 -dict=/src/tools/fuzz/pdf.dict -print_final_stats=1 \
    -artifact_prefix=/work/artifacts/ /work/corpus /work/seeds /src/tools/fuzz/regressions
rc=$?
set -e
echo "corpus: $(ls "$STATE/corpus" | wc -l) inputs; findings: $(ls "$STATE/artifacts" | wc -l)"
ls -l "$STATE/artifacts"
exit $rc
