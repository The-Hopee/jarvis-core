"""Call C++ functions directly through the exported C ABI, no extra process."""
import argparse
import ctypes
import json
from pathlib import Path

class NativeKernel:
    def __init__(self, library: Path):
        self.dll = ctypes.CDLL(str(library))
        self.dll.jarvis_create.argtypes = [ctypes.c_char_p]
        self.dll.jarvis_create.restype = ctypes.c_void_p
        self.dll.jarvis_execute.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        # Keep the original pointer so the same DLL can release its allocation.
        self.dll.jarvis_execute.restype = ctypes.c_void_p
        self.dll.jarvis_free_string.argtypes = [ctypes.c_void_p]
        self.dll.jarvis_free_string.restype = None
        self.dll.jarvis_destroy.argtypes = [ctypes.c_void_p]
        self.dll.jarvis_destroy.restype = None
        self.handle = self.dll.jarvis_create(b"{}")
        if not self.handle:
            raise RuntimeError("Native kernel initialization failed")

    def call(self, method: str, **params) -> dict:
        if not self.handle:
            raise RuntimeError("Kernel already closed")
        request = json.dumps({"id": "dll-client", "method": method, "params": params}, ensure_ascii=False).encode("utf-8")
        pointer = self.dll.jarvis_execute(self.handle, request)
        if not pointer:
            raise RuntimeError("Native response allocation failed")
        try:
            return json.loads(ctypes.string_at(pointer).decode("utf-8"))
        finally:
            self.dll.jarvis_free_string(pointer)

    def close(self):
        if self.handle:
            self.dll.jarvis_destroy(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dll", type=Path, default=Path(__file__).resolve().parents[1] / "build/bin/Release/jarvis_core.dll")
    args = parser.parse_args()
    with NativeKernel(args.dll) as kernel:
        print(json.dumps(kernel.call("system_snapshot", checks=["memory", "system"]), ensure_ascii=False, indent=2))
