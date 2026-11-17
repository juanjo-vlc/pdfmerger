# PDF Merger

> [!WARNING]
> **Personal project: no warranty, no liability.**
>
> I created this software for my own personal use and share it in the hope that others find
> it helpful. It is provided **"as is", without warranty of any kind**, express or implied,
> including fitness for a particular purpose. It is not a supported product and comes with no
> promise of maintenance, updates or support.
>
> **You use it entirely at your own risk.** The authors and contributors accept **no
> liability** for any damage or loss arising from its use. That includes lost, corrupted or
> leaked documents, wrong or incomplete output files, and security incidents. Please keep
> copies of your original files and check the exported PDFs before you rely on them,
> especially for important, confidential or legal documents.
>
> The full terms are in the [GNU Affero General Public License v3](LICENSE), sections 15
> ("Disclaimer of Warranty") and 16 ("Limitation of Liability").

A portable desktop application for **Windows 10 and 11** that opens several PDF files at once,
lets you rearrange their pages visually, and exports the result as a new PDF. You can set the
document properties and choose the output quality.

No installation is needed: unzip the folder and run `PDFMerger.exe`, for example from a USB stick.

## Features

- **Open many PDFs at once**: use *File ▸ Open*, drag files from Explorer onto the window, or
  drop them onto `PDFMerger.exe`. Each file gets its own color so you can see where every page
  came from.
- **Password-protected PDFs**: the app asks for the password when a file needs one.
- **Page operations**: drag and drop to reorder, plus move earlier/later/to start/to end,
  rotate left/right, duplicate, delete and reverse. Everything can be undone and redone.
- **Extract**: export only the selected pages.
- **Document properties**: title, author, subject, keywords, creator, producer, and creation
  and modification dates.
- **Output quality**:
  - presets: *Original*, *Print 300 dpi*, *eBook 150 dpi*, *Screen 72 dpi*, or *Custom*
  - image downsampling (target dpi and threshold)
  - JPEG recompression quality (10–100)
  - lossless optimization: remove unused or duplicate objects, compress streams, images and
    fonts, object streams, sanitize content
- **Encrypt the output** with AES-256: an open password, a permissions password, and
  print/copy/modify/annotate permissions. If you leave the permissions password empty, a
  random one is generated, so the restrictions can't be lifted with the open password.
- **Sanitize** (optional): remove links, form fields, JavaScript, attachments and XMP
  metadata coming from the input files. Recommended for files from untrusted sources.
- **Languages**: English, Español and Français. By default the app follows the Windows display
  language; you can change it under *View ▸ Language*.
- **Portable settings**: settings are saved in `settings.ini` next to the exe. If that folder
  is read-only, they go to `%APPDATA%\PDFMerger\settings.ini` instead. Nothing is written to
  the registry.

### Keyboard shortcuts

| Action | Shortcut |
|---|---|
| Open files | Ctrl+O |
| Export / export selection | Ctrl+S / Ctrl+Shift+S |
| Document properties | Ctrl+I |
| Undo / redo | Ctrl+Z / Ctrl+Y |
| Rotate right / left | Ctrl+R / Ctrl+Shift+R |
| Duplicate / delete | Ctrl+D / Del |
| Move earlier / later | Ctrl+↑ / Ctrl+↓ |
| Move to start / end | Ctrl+Home / Ctrl+End |
| Thumbnail size | Ctrl + mouse wheel |

### Command line (headless export)

```bat
PDFMerger.exe --export merged.pdf --preset ebook --title "Annual report" --sanitize ^
              --input-password-file input-passwords.txt --log export.log a.pdf b.pdf c.pdf
```

This joins all pages of the inputs in order. Other options:
- `--preset original|print|ebook|screen` and `--jpeg-quality N`
- `--author`, `--subject` and `--keywords`
- `--sanitize` to remove links, forms, JavaScript, attachments and XMP metadata
- `--password-file FILE` to encrypt the output with the password on the file's first line
- `--input-password-file FILE` for encrypted inputs, one password per line

Use `-` as the file name to read a password from standard input. Passwords can't be passed
directly on the command line, because other programs and shell history can see command lines.

The exit code is 0 on success. The Windows build has no console, so use `--log` to see
messages.

## Security notes

- **Sandboxed PDF processing.** PDF files are parsed by MuPDF, which is native code. The
  window you see never parses a PDF. All PDF work (opening, thumbnails, exporting) happens in
  a separate *worker* process, which on Windows runs:
  - at **low integrity**: it can read files but can't write to your folders or the registry,
    or control other programs' windows
  - inside a **job object**: memory capped at 2 GB (4 GB for exports), not allowed to start
    any program, no clipboard or desktop access, and killed automatically when the app closes
  - with **exploit mitigations**: mandatory ASLR, strict handle checks, heap termination, and
    no remote, low-labelled or legacy injected DLLs and no non-system fonts

  If the worker crashes or hangs on a file, it is restarted and the app reports that the file
  couldn't be processed safely. The app also checks everything the worker sends back, and
  writes the exported file itself.
- Check the sandbox on your own machine with:
  ```bat
  PDFMerger.exe --sandbox-selftest some.pdf --log selftest.txt
  ```
  The exit code is 0 if every check passed. If a corporate security policy prevents
  low-integrity processes, the worker falls back to a normal-integrity process with the
  other protections, and *Help ▸ About* says so. `PDFMERGER_NO_SANDBOX=1` forces that
  fallback, for troubleshooting only.
- Files over 2 GB, files with more than 10,000 pages, pages larger than 200 inches, and
  images over 400 megapixels are refused.
- Run the portable folder from a location only you can write to, for example under your user
  profile, not a shared network drive. Anyone who can write to the folder can replace the
  program's files.
- Download releases only from the project's GitHub releases page, and check the download
  against `SHA256SUMS` or with `gh attestation verify PDFMerger-<ver>-win64.zip --repo <owner>/<repo>`.
  The executable is not code-signed.

## Development

You need Python 3.10 or later. The `-e ".[dev]"` install below uses version ranges, which is fine
for development; release builds use the hash-locked files described further down.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"            # Windows: .venv\Scripts\pip ...
for f in src/pdfmerger/i18n/*.ts; do .venv/bin/pyside6-lrelease "$f"; done
.venv/bin/python -m pdfmerger some.pdf other.pdf
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
```

### Translations

All user-visible strings go through `self.tr()`. After you change UI text:

```bash
.venv/bin/pyside6-lupdate -no-obsolete $(find src/pdfmerger -name '*.py') \
    -ts src/pdfmerger/i18n/pdfmerger_{en,es,fr}.ts
.venv/bin/pyside6-linguist src/pdfmerger/i18n/pdfmerger_es.ts   # translate new entries
```

To add a language, create `pdfmerger_<code>.ts` and add the code to `LANGUAGES` in
`src/pdfmerger/i18n/__init__.py`. The `.qm` files are compiled at build time.

### Fuzzing

`tools/fuzz/` fuzzes the worker's PDF code path with [Atheris](https://github.com/google/atheris):
open, safety limits, thumbnails, and export (plain, sanitized, recompressed). It runs in
Docker with no network.

```bash
tools/fuzz/run.sh 600                     # fuzz for 10 minutes; corpus and findings in .fuzz/
tools/fuzz/run.sh repro .fuzz/artifacts/crash-…   # re-run a single finding
```

These count as findings:
- crashes, hangs and memory blow-ups
- an export that isn't a valid PDF or has the wrong page count
- JavaScript that survives *sanitize*

When you fix a finding, add the input to `tools/fuzz/regressions/` and add a unit test. The
`Nightly fuzzing` workflow runs for 30 minutes every night and uploads any findings.

## Building the portable Windows package

PyInstaller can only produce Windows executables when it runs on Windows (or under Wine).
Release builds install their dependencies from hash-locked files
(`requirements/windows-py312.lock`, `packaging/docker/requirements-build.lock`). After you
change a `.in` file, regenerate the locks with `tools/lock.sh` (needs `uv`) and review the
diff.

1. **GitHub Actions** (the only source of official releases): `.github/workflows/build.yml`
   builds on `windows-latest`, runs the tests and two smoke tests of the frozen exe, and
   uploads the zip and its `.sha256` file. Pushing a `v*` tag also publishes a GitHub release
   with `SHA256SUMS` and a signed build-provenance attestation. The workflow runs with
   read-only permissions; only the release job, which runs only on tags, can write.
2. **On a Windows machine**: clone the repo to a local folder (not a `\\wsl$` path), then run
   ```powershell
   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
   ```
   This needs Python 3.12 and produces `dist\PDFMerger-<version>-win64.zip` plus a `.sha256` file.
3. **Docker on Linux or WSL** (development builds only): this runs Windows Python and
   PyInstaller under Wine, as an unprivileged user:
   ```bash
   packaging/docker/build.sh               # RUN_TESTS=1 to also run tests under Wine
   ```
   It produces `dist/PDFMerger-<version>-win64-wine-dev.zip`. Real Windows containers would
   need a Windows host with Docker in Windows-container mode, so this image uses Wine instead.
   PySide6 6.10 and later need the ICU library (`icuuc.dll`) that Windows provides but Wine
   doesn't, so this build stays on PySide6 6.9.x, which no longer receives fixes. **Don't
   distribute these zips**; use them only for testing.

## License

PDF Merger is free software, licensed under the **GNU Affero General Public License v3.0 or
later** (see `LICENSE`). It uses [PyMuPDF](https://pymupdf.readthedocs.io/) (AGPL-3.0) and
[Qt for Python](https://www.qt.io/qt-for-python) (LGPL-3.0).
