#!/bin/bash
# Runs inside the Wine build container as the unprivileged "builder" user.
# The repository is mounted read-only at /src; the zip is written to /out.
set -euo pipefail

WORK=/home/builder/work
rm -rf "$WORK/src" "$WORK/dist" "$WORK/build" && mkdir -p "$WORK/src"
cp -a /src/. "$WORK/src/"
cd "$WORK/src"
rm -rf build dist .venv .venv-win

echo "==> Compiling translations"
for ts in src/pdfmerger/i18n/*.ts; do
    /usr/lib/qt6/bin/lrelease "$ts"
done

if [[ "${RUN_TESTS:-0}" == "1" ]]; then
    echo "==> Running tests (Windows Python under Wine)"
    QT_QPA_PLATFORM=offscreen \
        wine python -m pytest -q -p no:cacheprovider || { echo "tests failed"; exit 1; }
fi

echo "==> Running PyInstaller"
wine python -m PyInstaller --noconfirm --clean --distpath "$(winepath -w "$WORK/dist")" \
     --workpath "$(winepath -w "$WORK/build")" packaging/pdfmerger.spec

VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/pdfmerger/__init__.py)
# "-wine-dev" marks this as a development build: releases come from CI only.
ZIP="/out/PDFMerger-${VERSION}-win64-wine-dev.zip"
echo "==> Creating ${ZIP}"
rm -f "$ZIP"
(cd "$WORK/dist" && zip -qr9 "$ZIP" PDFMerger)
(cd /out && sha256sum "$(basename "$ZIP")" > "$(basename "$ZIP").sha256")
ls -l "$ZIP"
