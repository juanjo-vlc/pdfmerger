"""Exceptions shared by the GUI, the CLI and the worker process (no PyMuPDF import)."""


class PasswordRequired(Exception):
    """The document is encrypted and no valid password was given."""


class NotAPdf(Exception):
    """The file cannot be opened as a PDF."""


class UnsafePdf(Exception):
    """The file exceeds the safety limits (size, pages or image dimensions)."""


class ExportCancelled(Exception):
    pass


class WorkerError(Exception):
    """The worker reported an unexpected error."""


class WorkerCrashed(WorkerError):
    """The worker process died, hung or sent invalid data; it will be restarted."""


# error kind on the wire <-> exception class
ERROR_KINDS = {
    "password": PasswordRequired,
    "notpdf": NotAPdf,
    "unsafe": UnsafePdf,
    "cancelled": ExportCancelled,
    "value": ValueError,
}


def kind_of(exc: BaseException) -> str:
    for kind, cls in ERROR_KINDS.items():
        if isinstance(exc, cls):
            return kind
    return "error"
