# Fuzzing environment for the PDF worker code path (Linux; MuPDF behaves the same as on
# Windows for parsing). Runs as an unprivileged user with the repo mounted read-only.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/src/src
COPY tools/fuzz/requirements.lock /tmp/requirements.lock
RUN pip install --no-deps --require-hashes -r /tmp/requirements.lock

ARG FUZZ_UID=1000
RUN useradd --create-home --uid "${FUZZ_UID}" fuzzer
USER fuzzer
WORKDIR /work
ENTRYPOINT ["python", "/src/tools/fuzz/fuzz_pdf.py"]
