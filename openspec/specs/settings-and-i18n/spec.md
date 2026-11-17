# settings-and-i18n Specification

## Purpose
Keep the application portable: settings stay next to the executable and nothing is written to the registry. Offer the user interface in several languages.

## Requirements

### Requirement: Portable settings location
Settings SHALL be stored in `settings.ini` next to the executable when that file, or that folder, is writable. Otherwise they SHALL be stored in `%APPDATA%\PDFMerger\settings.ini` (on other platforms, `$XDG_CONFIG_HOME/PDFMerger/settings.ini`). The application SHALL NOT write to the Windows registry.

#### Scenario: Read-only folder
- **WHEN** the portable folder is read-only and has no `settings.ini`
- **THEN** settings are saved under `%APPDATA%\PDFMerger\`

### Requirement: Remembered state without secrets
The application SHALL remember the window state, the thumbnail size, the last open and save folders, the language, and the export options. It SHALL NOT store any password.

#### Scenario: Export options round-trip
- **WHEN** the user exports with the Screen preset and restarts the app
- **THEN** the export dialog opens with the Screen preset and empty password fields

### Requirement: User interface languages
The user interface SHALL be available in English, Spanish and French. By default it SHALL follow the system display language and fall back to English. View ▸ Language SHALL let the user pick a language or the system default, which takes effect at the next start. Language names SHALL be shown in their own language.

#### Scenario: Unsupported system language
- **WHEN** the system display language is German and no language is set
- **THEN** the interface is shown in English

#### Scenario: Change language
- **WHEN** the user picks Français under View ▸ Language
- **THEN** a message says the change applies at the next start, and the next start is in French
