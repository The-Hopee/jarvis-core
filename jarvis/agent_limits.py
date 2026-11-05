"""Admission capacity for cloud workers; task count and running processes differ."""
import ctypes
import os

def memory_available_mb():
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total',ctypes.c_ulonglong),
                  ('available',ctypes.c_ulonglong),('page_total',ctypes.c_ulonglong),('page_available',ctypes.c_ulonglong),
                  ('virtual_total',ctypes.c_ulonglong),('virtual_available',ctypes.c_ulonglong),('extended',ctypes.c_ulonglong)]
    status=Memory();status.length=ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):return 2048
    return status.available//(1024*1024)

def capacity(settings,*,cpus=None,available_mb=None):
    cpus=max(1,cpus if cpus is not None else os.cpu_count() or 1)
    available=max(0,available_mb if available_mb is not None else memory_available_mb())
    requested=settings.agent_workers or 4
    memory_slots=max(1,(available-1024)//settings.agent_memory_mb)
    return max(1,min(requested,cpus,memory_slots))
