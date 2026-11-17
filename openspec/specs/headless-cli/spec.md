# headless-cli Specification

## Purpose
Merge PDFs without the GUI, for scripting. The worker parses the PDFs exactly as it does for the GUI.

## Requirements

### Requirement: Headless export
`PDFMerger.exe --export OUT.pdf [options] IN1.pdf [IN2.pdf …]` SHALL concatenate all pages of the inputs in order and write `OUT.pdf` atomically, without opening a window. The supported options SHALL be `--preset original|print|ebook|screen`, `--jpeg-quality N`, `--title`, `--author`, `--subject`, `--keywords`, `--sanitize`, `--password-file`, `--input-password-file`, `--log` and `--version`. The producer metadata SHALL be set to the application name and version.

#### Scenario: Successful merge
- **WHEN** `--export out.pdf a.pdf b.pdf` is run with valid inputs
- **THEN** `out.pdf` holds the pages of `a.pdf` followed by those of `b.pdf`, the message `ok: wrote out.pdf (N pages, S bytes)` is printed, and the exit code is 0

### Requirement: Passwords only from files or stdin
The CLI SHALL NOT accept passwords as argument values. `--password-file FILE` SHALL encrypt the output with AES-256 using the first non-empty line of FILE. `--input-password-file FILE` SHALL provide passwords for encrypted inputs, one per line, each tried in turn. A FILE of `-` SHALL read from standard input, and only one of the two options MAY use `-`.

#### Scenario: Both options read stdin
- **WHEN** both `--password-file -` and `--input-password-file -` are given
- **THEN** the CLI prints an error and exits with code 2

#### Scenario: Empty output password file
- **WHEN** `--password-file` names an empty file
- **THEN** the CLI prints "the password file is empty" and exits with code 2

### Requirement: Exit codes and logging
The CLI SHALL exit with 0 on success, 2 on usage errors (including argument parsing errors and missing `--export` or inputs), and 1 on processing errors (an input that can't be opened, an output that is one of the inputs, or an export failure). With `--log FILE`, all messages SHALL be written to FILE, including argument parsing errors, because the Windows build has no console.

#### Scenario: Output equals an input
- **WHEN** `--export a.pdf a.pdf` is run
- **THEN** the CLI prints an error that the output is one of the inputs and exits with code 1

#### Scenario: Bad argument captured in log
- **WHEN** `--preset bogus --log out.txt` is run
- **THEN** `out.txt` contains the error and usage text and the exit code is 2
