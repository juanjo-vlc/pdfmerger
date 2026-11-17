# document-loading Specification

## Purpose
Open one or more PDF files into the working document. Each file is parsed only by the sandboxed worker and is checked against safety limits before any of its pages are used.

## Requirements

### Requirement: Open multiple PDF files
The application SHALL let the user open several PDF files at once through File ▸ Open (Ctrl+O), by dragging files onto the window, or by passing `.pdf` paths on the command line when it starts the GUI. The pages of every opened file SHALL be added to the working document in file order.

#### Scenario: Open files from the dialog
- **WHEN** the user selects `a.pdf` (2 pages) and `b.pdf` (3 pages) in the Open dialog
- **THEN** 5 pages are appended to the working document, those of `a.pdf` first
- **AND** a status message reports the number of pages added

#### Scenario: Drop files onto the page view
- **WHEN** the user drops PDF files from the file manager at a position in the page grid
- **THEN** their pages are inserted at that position

#### Scenario: Opening is undoable
- **WHEN** the user opens files and then chooses Undo
- **THEN** the pages of those files are removed and the files are closed

### Requirement: Source identification
Each opened file SHALL get its own color. Every page thumbnail SHALL show that color and its page number in the source file. The Files panel SHALL list each source with how many of its pages are in use.

#### Scenario: Page labels
- **WHEN** a page from `report.pdf` page 3 of 10 is shown
- **THEN** its tooltip reads "report.pdf — page 3 of 10" and its border uses the color of `report.pdf`

### Requirement: Password-protected inputs
When a file is encrypted, the application SHALL ask for its password. If the password is wrong it SHALL ask again, and if the user cancels it SHALL skip the file without an error.

#### Scenario: Wrong password then cancel
- **WHEN** the user enters a wrong password and then cancels the retry prompt
- **THEN** the file is not opened and the other files are still opened

### Requirement: Safety limits on input
The worker SHALL refuse a file larger than 2 GiB, a file with more than 10,000 pages, a page with a side larger than 57,600 points or an empty page box, and a referenced image larger than 400 megapixels. A refused file SHALL be reported to the user as refused for safety reasons.

#### Scenario: Oversized page count
- **WHEN** the user opens a PDF with 10,001 pages
- **THEN** the file is refused and the message says it was refused for safety reasons

### Requirement: Error reporting for unreadable files
Files that are missing, not valid PDFs, or that crash the worker SHALL be listed together in one warning after the other files have been opened. Untrusted text in that warning (file names and parser messages) SHALL be displayed as plain text.

#### Scenario: Mixed valid and invalid files
- **WHEN** the user opens `good.pdf` and `notes.txt`
- **THEN** `good.pdf` is opened and a single warning says `notes.txt` is not a valid PDF

### Requirement: Title prefill from the first input
When files are opened, the output title SHALL be prefilled from the opened file's title metadata, or from its file name when it has none. No other metadata field from the input files SHALL be copied over.

#### Scenario: Author is not inherited
- **WHEN** an input file has author "Alice"
- **THEN** the output document's author field stays empty unless the user sets it
