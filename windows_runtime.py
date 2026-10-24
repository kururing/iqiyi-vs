"""Small Windows API helpers so the app does not depend on PowerShell."""
from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes
from typing import NamedTuple


class Process(NamedTuple):
    pid: int
    name: str
    path: str
    command_line: str


def command_line_args(command: str) -> list[str]:
    """Parse Windows quoting exactly, including Unicode paths with spaces."""
    if os.name != "nt" or not command:
        return []
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    arguments = shell32.CommandLineToArgvW(command, ctypes.byref(count))
    if not arguments:
        return []
    try:
        return list(arguments[:count.value])
    finally:
        kernel32.LocalFree(arguments)


def create_named_mutex(name: str) -> wintypes.HANDLE | None:
    """Create a named Windows mutex; return None when unavailable or already running."""
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return None
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return None
    return handle


class _ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


class _ProcessBasicInformation(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_void_p), ("PebBaseAddress", ctypes.c_void_p),
        ("Reserved2", ctypes.c_void_p * 2), ("UniqueProcessId", ctypes.c_size_t),
        ("Reserved3", ctypes.c_void_p),
    ]


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int), ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", ctypes.c_void_p), ("dwHotKey", wintypes.DWORD),
        ("hIconMonitor", ctypes.c_void_p), ("hProcess", wintypes.HANDLE),
    ]


def _remote_command_line(kernel32, ntdll, handle) -> str:
    basic = _ProcessBasicInformation()
    status = ntdll.NtQueryInformationProcess(handle, 0, ctypes.byref(basic),
                                             ctypes.sizeof(basic), None)
    if status != 0 or not basic.PebBaseAddress:
        return ""

    wow64 = wintypes.BOOL()
    is_wow64 = ctypes.sizeof(ctypes.c_void_p) == 8 and bool(
        kernel32.IsWow64Process(handle, ctypes.byref(wow64)) and wow64.value)
    is_64_bit = ctypes.sizeof(ctypes.c_void_p) == 8 and not is_wow64
    peb_address = basic.PebBaseAddress
    if is_wow64:
        wow_peb = ctypes.c_void_p()
        status = ntdll.NtQueryInformationProcess(handle, 26, ctypes.byref(wow_peb),
                                                 ctypes.sizeof(wow_peb), None)
        if status != 0 or not wow_peb.value:
            return ""
        peb_address = wow_peb.value
    pointer_size = 8 if is_64_bit else 4
    peb_offset = 0x20 if is_64_bit else 0x10
    command_offset = 0x70 if is_64_bit else 0x40

    def read(address: int, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        count = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buffer,
                                          size, ctypes.byref(count)) or count.value != size:
            return b""
        return buffer.raw

    process_parameters = read(peb_address + peb_offset, pointer_size)
    if not process_parameters:
        return ""
    params_address = int.from_bytes(process_parameters, "little")
    buffer_offset = 8 if is_64_bit else 4
    unicode_string = read(params_address + command_offset, buffer_offset + pointer_size)
    if not unicode_string:
        return ""
    length = int.from_bytes(unicode_string[:2], "little")
    command_address = int.from_bytes(unicode_string[buffer_offset:buffer_offset + pointer_size], "little")
    raw = read(command_address, length) if command_address and length else b""
    return raw.decode("utf-16-le", errors="replace") if raw else ""


def list_processes(include_command_line: bool = True) -> list[Process]:
    """Return accessible process paths and command lines using Toolhelp/NT APIs."""
    if os.name != "nt":
        return []
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel32.IsWow64Process.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p,
                                               wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    ntdll.NtQueryInformationProcess.restype = wintypes.LONG

    snapshot = kernel32.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    if snapshot == wintypes.HANDLE(-1).value:
        return []
    processes = []
    try:
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            needs_command = include_command_line and entry.szExeFile.lower() in {"python.exe", "pythonw.exe"}
            handle = kernel32.OpenProcess(0x0410 if needs_command else 0x1000,
                                          False, entry.th32ProcessID)
            if not handle and needs_command:
                handle = kernel32.OpenProcess(0x1000, False, entry.th32ProcessID)
            if handle:
                try:
                    image = ctypes.create_unicode_buffer(32768)
                    size = wintypes.DWORD(len(image))
                    path = (image.value if kernel32.QueryFullProcessImageNameW(
                        handle, 0, image, ctypes.byref(size)) else "")
                    command = _remote_command_line(kernel32, ntdll, handle) if needs_command else ""
                    processes.append(Process(entry.th32ProcessID, entry.szExeFile, path, command))
                finally:
                    kernel32.CloseHandle(handle)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return processes


def terminate_process(pid: int, timeout: float = 10) -> bool:
    if os.name != "nt":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    handle = kernel32.OpenProcess(0x00100001, False, pid)  # SYNCHRONIZE | TERMINATE
    if not handle:
        return False
    try:
        if not kernel32.TerminateProcess(handle, 1):
            return False
        return kernel32.WaitForSingleObject(handle, max(0, int(timeout * 1000))) == 0
    finally:
        kernel32.CloseHandle(handle)


def run_elevated(executable: str, args: list[str], cwd: str,
                 timeout: float = 1800) -> subprocess.CompletedProcess:
    """Run a program through the native UAC prompt and return its exit code."""
    if os.name != "nt":
        raise OSError("Administrator elevation is available only on Windows.")
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = subprocess.list2cmdline(args)
    info.lpDirectory = cwd
    info.nShow = 0  # SW_HIDE
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == 1223:  # ERROR_CANCELLED
            return subprocess.CompletedProcess([executable, *args], 1223, "", "")
        raise ctypes.WinError(error)
    try:
        result = kernel32.WaitForSingleObject(info.hProcess, int(timeout * 1000))
        if result == 0x102:  # WAIT_TIMEOUT
            kernel32.TerminateProcess(info.hProcess, 1)
            kernel32.WaitForSingleObject(info.hProcess, 5000)
            raise subprocess.TimeoutExpired([executable, *args], timeout)
        code = wintypes.DWORD()
        if result != 0 or not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return subprocess.CompletedProcess([executable, *args], code.value, "", "")
    finally:
        kernel32.CloseHandle(info.hProcess)
