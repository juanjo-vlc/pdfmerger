# page-editing Specification

## Purpose
Arrange the pages of the working document visually. All edits can be undone.

## Requirements

### Requirement: Reorder pages
The user SHALL be able to reorder the selected pages by drag and drop and with the commands Move earlier (Ctrl+↑), Move later (Ctrl+↓), Move to beginning (Ctrl+Home), Move to end (Ctrl+End), and Reverse order.

#### Scenario: Move to beginning
- **WHEN** pages 4 and 6 are selected and the user presses Ctrl+Home
- **THEN** those pages become pages 1 and 2, in their previous relative order, and stay selected

#### Scenario: Reverse a selection
- **WHEN** pages 2–4 are selected and the user chooses Reverse order
- **THEN** they appear as 4, 3, 2 in the same positions

### Requirement: Rotate, duplicate and delete pages
The user SHALL be able to rotate the selected pages right (Ctrl+R) or left (Ctrl+Shift+R) by 90°, duplicate them (Ctrl+D), and delete them (Del). Rotation SHALL add to the page's own rotation, modulo 360.

#### Scenario: Rotate twice
- **WHEN** a page is rotated right twice
- **THEN** it is exported with 180° added to its original rotation

#### Scenario: Delete keeps a selection
- **WHEN** the user deletes selected pages and pages remain after them
- **THEN** the next remaining page is selected

### Requirement: Remove sources
The user SHALL be able to remove a file from the Files panel, which removes all its pages, and to close all files at once. Both actions SHALL be undoable.

#### Scenario: Undo removal of a file
- **WHEN** the user removes a file and then chooses Undo
- **THEN** the file is reopened and its pages return to their previous positions

### Requirement: Undo and redo
Every page edit SHALL be recorded on an undo stack with a descriptive label. The user SHALL be able to undo (Ctrl+Z) and redo (Ctrl+Y or the platform redo shortcut).

#### Scenario: Undo label
- **WHEN** the user deletes 3 pages
- **THEN** the Undo tooltip reads "Undo: Delete 3 pages"

### Requirement: Thumbnail size
The user SHALL be able to change the thumbnail size between 80 and 400 pixels with Ctrl + mouse wheel, the zoom commands, or the status-bar control. Thumbnails SHALL be rendered in the background by the worker.

#### Scenario: Zoom clamp
- **WHEN** the user keeps zooming in past the maximum
- **THEN** the thumbnail size stays at 400 pixels
