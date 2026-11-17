# Windows build environment on a Linux Docker host: Windows CPython + PyInstaller under Wine.
# The resulting PDFMerger.exe is a native Windows executable, intended for development and
# testing. Official releases are built by CI on real Windows (see .github/workflows/build.yml).
#
# Note: genuine Windows containers need a Windows host with Docker in Windows-container
# mode; this image works anywhere Linux containers run (WSL2, Linux, macOS, CI).
FROM tobix/pywine:3.14@sha256:adbb25c76313f5e4d29a9874ddc4ffd963504ac63e794d55ae52279d77cc2009

ENV WINEDEBUG=-all \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Native Linux tools: lrelease (the Windows one needs DLLs Wine lacks) and zip.
RUN apt-get update \
 && apt-get install -y --no-install-recommends qt6-l10n-tools=6.8.2-5 zip=3.0-15+deb13u1 \
 && rm -rf /var/lib/apt/lists/*

# Build as an unprivileged user whose UID matches the host user, so the output needs no
# chown. Wine only runs a prefix owned by the current user, hence the chown.
ARG BUILD_UID=1000
RUN useradd --create-home --uid "${BUILD_UID}" builder \
 && chown -R builder /opt/wineprefix
USER builder

# Hash-locked toolchain. --no-deps: the lock is complete, and PyMuPDF's unused AI
# extras (numpy, onnxruntime, ...) are deliberately left out of it.
COPY --chown=builder packaging/docker/requirements-build.lock /tmp/requirements-build.lock
RUN wine python -m pip install --no-deps --require-hashes -r Z:\\tmp\\requirements-build.lock \
 && wine python -c "import pymupdf, PySide6.QtWidgets; print('toolchain ok', pymupdf.VersionBind)"

COPY --chown=builder packaging/docker/entrypoint.sh /home/builder/build-pdfmerger
WORKDIR /home/builder/work
ENTRYPOINT ["/bin/bash", "/home/builder/build-pdfmerger"]
