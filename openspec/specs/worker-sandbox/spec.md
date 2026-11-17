# worker-sandbox Specification

## Purpose
Contain MuPDF, the native code that parses untrusted PDFs, in a separate, restricted worker process. A malicious PDF must not be able to compromise the user's session.

## Requirements

### Requirement: Process separation
All PDF parsing, rendering and export building SHALL happen in a worker process started as `--worker`. The worker SHALL NOT load Qt. The GUI and the CLI SHALL NOT import PyMuPDF. The worker SHALL communicate only over length-framed stdin/stdout messages, with the JSON header limited to 4 MiB and the payload to just under 3 GiB, and SHALL NOT write the user's files.

#### Scenario: Stray output does not corrupt the protocol
- **WHEN** native code in the worker prints to standard output
- **THEN** the text goes to stderr and the protocol stream stays intact

### Requirement: Windows sandbox
On Windows, the frozen executable SHALL start the worker at low integrity inside a job object. The job object SHALL cap memory at 2 GiB for rendering and 4 GiB for exports, forbid child processes, apply all UI restrictions, and kill the worker when the application closes. The worker SHALL also start with these mitigations: bottom-up and high-entropy ASLR, strict handle checks, heap termination, extension point disable, non-system font blocking, and blocking of remote and low-labelled images.

#### Scenario: Write attempt from the worker
- **WHEN** the sandboxed worker tries to create a file in the user's profile, temp or Documents folder
- **THEN** the write is denied

### Requirement: Sandbox fallbacks
If a low-integrity process can't be created (for example, because of a corporate policy), the worker SHALL run at normal integrity with the job object and mitigations, and Help ▸ About SHALL say so. `PDFMERGER_NO_SANDBOX=1` SHALL force this fallback. When running from source on Windows, the worker SHALL be a plain separate process. On other platforms it SHALL be a separate process with an address-space limit.

#### Scenario: About shows the level
- **WHEN** the worker runs in the job-only fallback
- **THEN** Help ▸ About describes it as a separate process with resource limits

### Requirement: Untrusted replies and crash containment
The caller SHALL validate every reply from the worker: the reply id, the page-count range, the size of metadata strings, the thumbnail dimensions and buffer length, and that an export starts with `%PDF-`. If the worker exits, sends malformed data, or exceeds its per-operation timeout, the caller SHALL kill it, report that the file could not be processed safely, and on the next request start a new worker and reopen the previously open sources.

#### Scenario: Worker hang
- **WHEN** the worker doesn't answer a render request within 60 seconds
- **THEN** it is killed, the request fails with a worker-crashed error, and the next request starts a new worker

### Requirement: Sandbox self-test
`PDFMerger.exe --sandbox-selftest [sample.pdf …] [--log FILE]` SHALL start a worker as the application does. On Windows, it SHALL check that the worker runs at low integrity, can't write to the user's folders, and can't start programs. On all platforms, it SHALL check that the memory limit is enforced, that a crash and a hang are contained and followed by a restart, and that each sample opens and renders. It SHALL exit with 0 only if every check passes.

#### Scenario: Self-test in CI
- **WHEN** the release workflow runs the self-test on the frozen exe
- **THEN** every check prints PASS and the exit code is 0
