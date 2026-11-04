"""Session-local Windows ownership and graceful shutdown for the assistant."""
import ctypes
from ctypes import wintypes
import hashlib
import os
import time

from .config import ROOT

_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel.CreateMutexW.restype = wintypes.HANDLE
_kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel.OpenMutexW.restype = wintypes.HANDLE
_kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
_kernel.ReleaseMutex.restype = wintypes.BOOL
_kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel.CreateEventW.restype = wintypes.HANDLE
_kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel.OpenEventW.restype = wintypes.HANDLE
_kernel.SetEvent.argtypes = [wintypes.HANDLE]
_kernel.SetEvent.restype = wintypes.BOOL
_kernel.ResetEvent.argtypes = [wintypes.HANDLE]
_kernel.ResetEvent.restype = wintypes.BOOL
_kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel.WaitForSingleObject.restype = wintypes.DWORD
_kernel.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel.CloseHandle.restype = wintypes.BOOL

DEFAULT_NAME = "Local\\Jarvis.Home." + hashlib.sha256(os.path.normcase(str(ROOT)).encode("utf-8")).hexdigest()[:20]


class AlreadyRunning(RuntimeError):
    pass


class RuntimeOwner:
    def __init__(self, name=DEFAULT_NAME):
        self.name = name
        self.mutex = self.event = None

    def __enter__(self):
        self.mutex = _kernel.CreateMutexW(None, False, self.name + ".owner")
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        wait = _kernel.WaitForSingleObject(self.mutex, 0)
        if wait not in (0, 0x80):  # signaled / abandoned after a crashed owner
            _kernel.CloseHandle(self.mutex)
            self.mutex = None
            if wait == 0x102:
                raise AlreadyRunning("Джарвис уже работает. Для проверки в консоли: .\\manage.cmd foreground")
            raise ctypes.WinError(ctypes.get_last_error())
        self.event = _kernel.CreateEventW(None, True, False, self.name + ".stop")
        if not self.event:
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)
        if not _kernel.ResetEvent(self.event):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)
        return self

    def stopped(self):
        return bool(self.event and _kernel.WaitForSingleObject(self.event, 0) == 0)

    def close(self):
        if self.event:
            _kernel.CloseHandle(self.event)
            self.event = None
        if self.mutex:
            _kernel.ReleaseMutex(self.mutex)
            _kernel.CloseHandle(self.mutex)
            self.mutex = None

    def __exit__(self, *_):
        self.close()


def is_running(name=DEFAULT_NAME):
    handle = _kernel.OpenMutexW(0x00100000, False, name + ".owner")
    if not handle:
        error = ctypes.get_last_error()
        if error == 2:
            return False
        raise ctypes.WinError(error)
    _kernel.CloseHandle(handle)
    return True


def request_stop(name=DEFAULT_NAME, timeout=60):
    handle = _kernel.OpenEventW(0x0002, False, name + ".stop")
    if not handle:
        error = ctypes.get_last_error()
        if error == 2 and not is_running(name):
            return True
        raise ctypes.WinError(error)
    try:
        if not _kernel.SetEvent(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        _kernel.CloseHandle(handle)
    deadline = time.monotonic() + timeout
    while is_running(name):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True
