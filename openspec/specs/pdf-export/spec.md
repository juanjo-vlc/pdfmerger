# pdf-export Specification

## Purpose
Write the working document, or the selected pages, to a new PDF file with user-defined properties, quality settings, optional sanitization and optional encryption.

## Requirements

### Requirement: Export all or selected pages
The user SHALL be able to export all pages (Ctrl+S) or only the selected pages (Ctrl+Shift+S) to a new PDF, in the current order and with the current rotations. The worker SHALL build the file in memory, and the GUI SHALL write it atomically (a temporary file, then a rename).

#### Scenario: Export selection
- **WHEN** 3 of 10 pages are selected and the user chooses Export selected pages
- **THEN** the output contains exactly those 3 pages in their on-screen order

#### Scenario: Cancel export
- **WHEN** the user presses Cancel during an export
- **THEN** the worker is stopped, no output file is written, and the status bar says the export was cancelled

### Requirement: Output must not overwrite an input
The application SHALL refuse to export to a path that refers to one of the open input files, including through links or differences in letter case on Windows.

#### Scenario: Same file chosen
- **WHEN** the user picks `a.pdf` as the output while `a.pdf` is open
- **THEN** a warning asks for a different name and nothing is written

### Requirement: Document properties
The user SHALL be able to set title, author, subject, keywords, creator, producer, creation date and modification date (Ctrl+I). If the modification date is empty it SHALL be set to the export time, and if the creation date is empty it SHALL be set to the modification date.

#### Scenario: Default dates
- **WHEN** the user exports without setting any dates
- **THEN** the creation and modification dates both equal the export time

### Requirement: Quality presets
The export dialog SHALL offer the presets Original (no image changes), Print (300 dpi, JPEG 90), eBook (150 dpi, JPEG 80), Screen (72 dpi, JPEG 60), and Custom. In a preset, images above 1.5× the target dpi SHALL be downsampled to the target dpi.

#### Scenario: eBook preset
- **WHEN** the user exports with the eBook preset
- **THEN** images above 225 dpi are resampled to 150 dpi and re-encoded as JPEG at quality 80

### Requirement: Custom quality options
Custom SHALL expose the downsampling target and threshold, the JPEG quality (10–100), and the lossless optimizations. The last options used SHALL be remembered, except for passwords.

#### Scenario: Passwords not persisted
- **WHEN** the user exports with encryption and then reopens the export dialog
- **THEN** the password fields are empty

### Requirement: Sanitize
When sanitize is enabled, the export SHALL drop links, form fields, JavaScript, open and additional actions, attachments, embedded files, page thumbnails, and XMP metadata coming from the inputs.

#### Scenario: JavaScript removed
- **WHEN** an input contains document JavaScript and the user exports with sanitize enabled
- **THEN** the output contains no JavaScript and no OpenAction or AA entries

### Requirement: Encryption
The user SHALL be able to encrypt the output with AES-256, with an open password, a permissions password, and print, copy, modify and annotate permissions. If no permissions password is given, the export SHALL use a random unguessable one.

#### Scenario: Restrictions without owner password
- **WHEN** the user sets an open password, disables printing, and leaves the permissions password empty
- **THEN** the output requires the open password and printing cannot be enabled with that password alone

### Requirement: Verified output
Before writing (and before encrypting), the exporter SHALL check that the produced PDF opens without repair, that every object is readable, and that the page count is correct. If the output is damaged, it SHALL retry without object streams and with MuPDF's repair. If the output is still damaged, it SHALL fail with a message suggesting to exclude the damaged pages.

#### Scenario: Damaged input object
- **WHEN** an input page contains an object MuPDF cannot copy cleanly and no retry fixes it
- **THEN** the export fails with the damaged-data message and no file is written
