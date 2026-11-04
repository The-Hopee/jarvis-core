"""Python collector boundary: execute native C++ and decode its JSON response."""
import argparse
import json
from pathlib import Path
import subprocess

def call_kernel(executable: Path, method: str, params: dict | None = None) -> dict:
    request = {"id": "python-collector", "method": method, "params": params or {}}
    completed = subprocess.run(
        [str(executable), "--request", json.dumps(request, ensure_ascii=False)],
        capture_output=True, text=True, encoding="utf-8", timeout=15, check=False,
    )
    if not completed.stdout:
        raise RuntimeError(completed.stderr.strip() or "Native kernel produced no response")
    response = json.loads(completed.stdout)
    if not response.get("ok"):
        raise RuntimeError(f"Native kernel error: {response.get('error')}")
    if completed.returncode:
        raise RuntimeError(f"Unexpected native exit code {completed.returncode}")
    if response.get("id") != request["id"] or response.get("protocol_version") != 1:
        raise RuntimeError("Native response does not match request/protocol")
    return response

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=Path(__file__).resolve().parents[1] / "build/bin/Release/jarvis-core.exe")
    args = parser.parse_args()
    print(json.dumps(call_kernel(args.exe, "system_snapshot", {"checks": ["cpu", "memory", "system"]}), ensure_ascii=False, indent=2))
