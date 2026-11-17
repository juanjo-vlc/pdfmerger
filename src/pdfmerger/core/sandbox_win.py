"""Start the PDF worker in a restricted Windows process (ctypes only, no extra deps).

Layers applied to the worker:

* **Low integrity level**: the process can read the user's files but cannot write to
  them, to the registry (outside LocalLow) or to normal-integrity processes and windows.
* **Job object**: memory cap per process, no child processes, no clipboard/desktop/
  global-atom access, and the worker dies when the GUI closes its job handle (or dies).
* **Process mitigation policies**: no legacy extension-point DLLs, no remote or
  low-integrity-labelled DLLs, no non-system fonts, strict handle checks, heap
  termination on corruption and mandatory (high-entropy) ASLR.
* Only the two pipe handles are inherited (``PROC_THREAD_ATTRIBUTE_HANDLE_LIST``).

If the low-integrity launch is refused by the system (e.g. by a corporate policy), the
worker is started at the normal integrity level with all the other layers, and
``SandboxedProcess.level`` says so.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes as wt
from typing import Optional

if sys.platform == "win32":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

# --- constants ---------------------------------------------------------------------
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
PROC_THREAD_ATTRIBUTE_MITIGATION_POLICY = 0x00020007
PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY = 0x0002000E
PROCESS_CREATION_CHILD_PROCESS_RESTRICTED = 0x01

# PROCESS_CREATION_MITIGATION_POLICY_* (first DWORD64).
# Win32k lockdown (1 << 28) is deliberately absent: PyInstaller's launcher loads
# user32.dll, whose initialisation fails once Win32k system calls are blocked. The job
# object's UI restrictions plus the low integrity level (UIPI) cover most of that ground.
MITIGATION_FLAGS = {
    "heap_terminate": 0x1 << 12,
    "bottom_up_aslr": 0x1 << 16,
    "high_entropy_aslr": 0x1 << 20,
    "strict_handle_checks": 0x1 << 24,
    "extension_point_disable": 0x1 << 32,
    "font_disable": 0x1 << 48,
    "image_no_remote": 0x1 << 52,
    "image_no_low_label": 0x1 << 56,
}

TOKEN_QUERY = 0x0008
TOKEN_DUPLICATE = 0x0002
TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_ADJUST_DEFAULT = 0x0080
SecurityImpersonation = 2
TokenPrimary = 1
TokenIntegrityLevel = 25
SE_GROUP_INTEGRITY = 0x00000020
LOW_INTEGRITY_SID = "S-1-16-4096"

JobObjectBasicUIRestrictions = 4
JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_UILIMIT_ALL = 0x000000FF

INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
STILL_ACTIVE = 259


# --- structures ----------------------------------------------------------------------
class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wt.DWORD), ("lpSecurityDescriptor", wt.LPVOID),
                ("bInheritHandle", wt.BOOL)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR),
                ("lpTitle", wt.LPWSTR), ("dwX", wt.DWORD), ("dwY", wt.DWORD),
                ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD), ("dwXCountChars", wt.DWORD),
                ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE),
                ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE)]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wt.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD),
                ("SchedulingClass", wt.DWORD)]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


class JOBOBJECT_BASIC_UI_RESTRICTIONS(ctypes.Structure):
    _fields_ = [("UIRestrictionsClass", wt.DWORD)]


def _check(ok, what: str):
    if not ok:
        err = ctypes.get_last_error()
        raise OSError(err, f"{what} failed: {ctypes.FormatError(err).strip()}")
    return ok


def _setup_prototypes() -> None:
    k, a = kernel32, advapi32
    k.CreatePipe.argtypes = [ctypes.POINTER(wt.HANDLE), ctypes.POINTER(wt.HANDLE),
                             ctypes.POINTER(SECURITY_ATTRIBUTES), wt.DWORD]
    k.SetHandleInformation.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD]
    k.CloseHandle.argtypes = [wt.HANDLE]
    k.GetCurrentProcess.restype = wt.HANDLE
    k.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wt.DWORD, wt.DWORD,
                                                    ctypes.POINTER(ctypes.c_size_t)]
    k.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.c_size_t,
                                            ctypes.c_void_p, ctypes.c_size_t,
                                            ctypes.c_void_p, ctypes.c_void_p]
    k.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    k.CreateJobObjectW.restype = wt.HANDLE
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
    k.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    k.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    k.ResumeThread.argtypes = [wt.HANDLE]
    k.ResumeThread.restype = wt.DWORD
    k.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    k.WaitForSingleObject.restype = wt.DWORD
    k.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    k.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                 wt.BOOL, wt.DWORD, ctypes.c_void_p, wt.LPCWSTR,
                                 ctypes.POINTER(STARTUPINFOEXW),
                                 ctypes.POINTER(PROCESS_INFORMATION)]
    k.LocalFree.argtypes = [ctypes.c_void_p]
    a.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    a.DuplicateTokenEx.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p, ctypes.c_int,
                                   ctypes.c_int, ctypes.POINTER(wt.HANDLE)]
    a.ConvertStringSidToSidW.argtypes = [wt.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    a.GetLengthSid.argtypes = [ctypes.c_void_p]
    a.GetLengthSid.restype = wt.DWORD
    a.SetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    a.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
                                      ctypes.POINTER(wt.DWORD)]
    a.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    a.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    a.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wt.DWORD]
    a.GetSidSubAuthority.restype = ctypes.POINTER(wt.DWORD)
    a.CreateProcessAsUserW.argtypes = [wt.HANDLE, wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p,
                                       ctypes.c_void_p, wt.BOOL, wt.DWORD, ctypes.c_void_p,
                                       wt.LPCWSTR, ctypes.POINTER(STARTUPINFOEXW),
                                       ctypes.POINTER(PROCESS_INFORMATION)]


if sys.platform == "win32":
    _setup_prototypes()


# --- helpers ---------------------------------------------------------------------------
def current_integrity_level() -> str:
    """'low', 'medium', 'high', 'system' or 'n/a' (non-Windows)."""
    if sys.platform != "win32":
        return "n/a"
    tok = wt.HANDLE()
    _check(advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY,
                                     ctypes.byref(tok)), "OpenProcessToken")
    try:
        need = wt.DWORD()
        advapi32.GetTokenInformation(tok, TokenIntegrityLevel, None, 0, ctypes.byref(need))
        buf = ctypes.create_string_buffer(need.value)
        _check(advapi32.GetTokenInformation(tok, TokenIntegrityLevel, buf, need,
                                            ctypes.byref(need)), "GetTokenInformation")
        sid = ctypes.cast(buf, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents.Label.Sid
        count = advapi32.GetSidSubAuthorityCount(sid).contents.value
        rid = advapi32.GetSidSubAuthority(sid, count - 1).contents.value
    finally:
        kernel32.CloseHandle(tok)
    if rid < 0x2000:
        return "low" if rid >= 0x1000 else "untrusted"
    if rid < 0x3000:
        return "medium"
    return "high" if rid < 0x4000 else "system"


def _low_integrity_token() -> wt.HANDLE:
    cur = wt.HANDLE()
    _check(advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                     TOKEN_DUPLICATE | TOKEN_QUERY | TOKEN_ADJUST_DEFAULT
                                     | TOKEN_ASSIGN_PRIMARY, ctypes.byref(cur)), "OpenProcessToken")
    new = wt.HANDLE()
    try:
        _check(advapi32.DuplicateTokenEx(cur, TOKEN_DUPLICATE | TOKEN_QUERY | TOKEN_ADJUST_DEFAULT
                                         | TOKEN_ASSIGN_PRIMARY, None, SecurityImpersonation,
                                         TokenPrimary, ctypes.byref(new)), "DuplicateTokenEx")
    finally:
        kernel32.CloseHandle(cur)
    sid = ctypes.c_void_p()
    _check(advapi32.ConvertStringSidToSidW(LOW_INTEGRITY_SID, ctypes.byref(sid)),
           "ConvertStringSidToSid")
    try:
        tml = TOKEN_MANDATORY_LABEL(SID_AND_ATTRIBUTES(sid, SE_GROUP_INTEGRITY))
        size = ctypes.sizeof(tml) + advapi32.GetLengthSid(sid)
        if not advapi32.SetTokenInformation(new, TokenIntegrityLevel, ctypes.byref(tml), size):
            err = ctypes.get_last_error()
            kernel32.CloseHandle(new)
            raise OSError(err, "SetTokenInformation failed")
    finally:
        kernel32.LocalFree(sid)
    return new


def _create_job(memory_limit: int) -> wt.HANDLE:
    job = kernel32.CreateJobObjectW(None, None)
    _check(job, "CreateJobObject")
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        | (JOB_OBJECT_LIMIT_PROCESS_MEMORY if memory_limit else 0))
    info.BasicLimitInformation.ActiveProcessLimit = 1     # the worker itself, nothing else
    info.ProcessMemoryLimit = memory_limit
    _check(kernel32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                            ctypes.byref(info), ctypes.sizeof(info)),
           "SetInformationJobObject(limits)")
    ui = JOBOBJECT_BASIC_UI_RESTRICTIONS(JOB_OBJECT_UILIMIT_ALL)
    _check(kernel32.SetInformationJobObject(job, JobObjectBasicUIRestrictions,
                                            ctypes.byref(ui), ctypes.sizeof(ui)),
           "SetInformationJobObject(ui)")
    return job


def _pipe(child_reads: bool) -> tuple[wt.HANDLE, wt.HANDLE]:
    """Return (child_end, parent_end); only the child end is inheritable."""
    sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    r, w = wt.HANDLE(), wt.HANDLE()
    _check(kernel32.CreatePipe(ctypes.byref(r), ctypes.byref(w), ctypes.byref(sa), 1 << 20),
           "CreatePipe")
    child, parent = (r, w) if child_reads else (w, r)
    _check(kernel32.SetHandleInformation(parent, HANDLE_FLAG_INHERIT, 0), "SetHandleInformation")
    return child, parent


class SandboxedProcess:
    """A minimal ``subprocess.Popen``-like wrapper around the sandboxed worker."""

    def __init__(self, hprocess, pid: int, job, stdin, stdout, level: str, mitigations: list[str]):
        self._hprocess = hprocess
        self._job = job
        self.pid = pid
        self.stdin = stdin
        self.stdout = stdout
        self.level = level              # "low-integrity" or "job-only"
        self.mitigations = mitigations
        self.returncode: Optional[int] = None

    def poll(self) -> Optional[int]:
        if self.returncode is None and self._hprocess:
            if kernel32.WaitForSingleObject(self._hprocess, 0) == WAIT_OBJECT_0:
                code = wt.DWORD()
                kernel32.GetExitCodeProcess(self._hprocess, ctypes.byref(code))
                self.returncode = code.value
        return self.returncode

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        ms = INFINITE if timeout is None else int(timeout * 1000)
        if kernel32.WaitForSingleObject(self._hprocess, ms) == WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired("worker", timeout)
        return self.poll()

    def kill(self) -> None:
        if self.poll() is None:
            kernel32.TerminateProcess(self._hprocess, 1)

    def close(self) -> None:
        for f in (self.stdin, self.stdout):
            try:
                f.close()
            except Exception:
                pass
        self.kill()
        if self._hprocess:
            self.wait(5)
            kernel32.CloseHandle(self._hprocess)
            self._hprocess = None
        if self._job:
            kernel32.CloseHandle(self._job)    # KILL_ON_JOB_CLOSE: nothing survives
            self._job = None


def _attribute_list(handles, mitigation: int):
    count = 3
    size = ctypes.c_size_t()
    kernel32.InitializeProcThreadAttributeList(None, count, 0, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    _check(kernel32.InitializeProcThreadAttributeList(buf, count, 0, ctypes.byref(size)),
           "InitializeProcThreadAttributeList")
    keep = []   # the attribute values must stay alive until CreateProcess returns
    harr = (wt.HANDLE * len(handles))(*handles)
    keep.append(harr)
    _check(kernel32.UpdateProcThreadAttribute(buf, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                              harr, ctypes.sizeof(harr), None, None),
           "UpdateProcThreadAttribute(handles)")
    pol = (ctypes.c_uint64 * 1)(mitigation)
    keep.append(pol)
    _check(kernel32.UpdateProcThreadAttribute(buf, 0, PROC_THREAD_ATTRIBUTE_MITIGATION_POLICY,
                                              pol, ctypes.sizeof(pol), None, None),
           "UpdateProcThreadAttribute(mitigation)")
    child = wt.DWORD(PROCESS_CREATION_CHILD_PROCESS_RESTRICTED)
    keep.append(child)
    _check(kernel32.UpdateProcThreadAttribute(buf, 0, PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY,
                                              ctypes.byref(child), ctypes.sizeof(child), None, None),
           "UpdateProcThreadAttribute(child)")
    return buf, keep


SEM_FAILCRITICALERRORS = 0x0001
SEM_NOGPFAULTERRORBOX = 0x0002
SEM_NOOPENFILEERRORBOX = 0x8000
QUIET_ERROR_MODE = SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX


def quiet_error_mode() -> None:
    """No Windows error pop-ups ("application was unable to start", crash dialogs) for
    this process or the workers it starts (children inherit the error mode). A worker
    that fails must just exit; the app reports the problem itself."""
    if sys.platform == "win32":
        kernel32.SetErrorMode(QUIET_ERROR_MODE)


def launch(argv: list[str], memory_limit: int, mitigations: Optional[list[str]] = None,
           low_integrity: bool = True) -> SandboxedProcess:
    import msvcrt

    quiet_error_mode()

    names = list(MITIGATION_FLAGS) if mitigations is None else list(mitigations)
    mitigation = 0
    for n in names:
        mitigation |= MITIGATION_FLAGS[n]
    cmdline = subprocess.list2cmdline(argv)

    in_child, in_parent = _pipe(child_reads=True)
    out_child, out_parent = _pipe(child_reads=False)
    nul = os.open(os.devnull, os.O_WRONLY)
    err_child = wt.HANDLE(msvcrt.get_osfhandle(nul))
    kernel32.SetHandleInformation(err_child, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT)

    job = _create_job(memory_limit)
    attrs, keep = _attribute_list([in_child, out_child, err_child], mitigation)
    si = STARTUPINFOEXW()
    si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
    si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
    si.StartupInfo.hStdInput = in_child
    si.StartupInfo.hStdOutput = out_child
    si.StartupInfo.hStdError = err_child
    si.lpAttributeList = ctypes.cast(attrs, ctypes.c_void_p)
    pi = PROCESS_INFORMATION()
    flags = (CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT
             | EXTENDED_STARTUPINFO_PRESENT)
    level = "job-only"
    try:
        created = False
        if low_integrity:
            try:
                token = _low_integrity_token()
                try:
                    created = bool(advapi32.CreateProcessAsUserW(
                        token, None, ctypes.create_unicode_buffer(cmdline), None, None, True,
                        flags, None, None, ctypes.byref(si), ctypes.byref(pi)))
                finally:
                    kernel32.CloseHandle(token)
                if created:
                    level = "low-integrity"
            except OSError:
                created = False
        if not created:
            _check(kernel32.CreateProcessW(None, ctypes.create_unicode_buffer(cmdline), None,
                                           None, True, flags, None, None, ctypes.byref(si),
                                           ctypes.byref(pi)), "CreateProcess")
        if not kernel32.AssignProcessToJobObject(job, pi.hProcess):
            err = ctypes.get_last_error()
            kernel32.TerminateProcess(pi.hProcess, 1)
            raise OSError(err, "AssignProcessToJobObject failed")
        kernel32.ResumeThread(pi.hThread)
        kernel32.CloseHandle(pi.hThread)
    except BaseException:
        kernel32.CloseHandle(job)
        for h in (in_parent, out_parent):
            kernel32.CloseHandle(h)
        raise
    finally:
        kernel32.DeleteProcThreadAttributeList(attrs)
        del keep
        for h in (in_child, out_child):
            kernel32.CloseHandle(h)
        os.close(nul)

    stdin = os.fdopen(msvcrt.open_osfhandle(in_parent.value, 0), "wb", buffering=1 << 16)
    stdout = os.fdopen(msvcrt.open_osfhandle(out_parent.value, os.O_RDONLY), "rb", buffering=1 << 16)
    return SandboxedProcess(pi.hProcess, pi.dwProcessId, job, stdin, stdout, level, names)
