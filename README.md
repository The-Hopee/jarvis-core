# Jarvis Core

Native Windows C++ kernel for a personal Jarvis assistant. Stage 1: local system
metrics, desktop actions, structured JSON, and Python integration.

The implementation adapts the `system_doctor` probes and follows the command
separation reviewed in `evo-wnd`. Source revision and individual file hashes are
recorded in [docs/PROVENANCE.md](docs/PROVENANCE.md).

## Build and run

Windows x64, Visual Studio 2022 with Desktop development with C++, Windows SDK,
CMake 3.24+, Git. Python 3.10+ is used for integration tests/examples. No Python
packages are required. Initial CMake configuration downloads nlohmann/json at a
pinned commit (v3.11.3).

```powershell
cmake -S . -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release --parallel
ctest --test-dir build -C Release --output-on-failure
python examples/read_snapshot.py
python examples/ctypes_snapshot.py
```

Artifacts: `build/bin/Release/jarvis-core.exe` and `jarvis_core.dll`.
The Python examples demonstrate both process isolation and direct C++ function
calls through a stable C ABI.

## Commands

| Method | Result | Changes system state |
|---|---|---|
| `ping` | Native version and readiness | No |
| `capabilities` | Tool descriptions, parameter schemas, enabled flags | No |
| `system_snapshot` | Selected metrics and threshold diagnostics | No |
| `list_processes` | Bounded top processes by CPU and working set | No |
| `list_windows` | Visible top-level windows, PID, title, executable | No |
| `get_audio` | Default playback endpoint volume/mute | No |
| `launch_app` | Launch a registered executable; return PID | Yes |
| `stop_app` | Terminate a child launched by this kernel instance | Yes |
| `focus_window` | Request activation; report whether it succeeded | Yes |
| `set_volume` | Set default playback volume, 0–100% | Yes |
| `set_mute` | Set default playback mute | Yes |

Mutating methods are disabled by default. The trusted local controller enables
them at kernel startup using configuration or `--enable-actions`. Request JSON
cannot enable them. Built-in application IDs: `notepad`, `calc`, `mspaint`.
Register additional executable paths using a local configuration file, based on
`config.example.json`. Arguments are fixed in that startup configuration, not
accepted from individual launch requests. `process_created` reports process
creation; it does not claim that the application's UI has finished loading.
`stop_app` uses the retained process handle, not an arbitrary PID supplied by a model.
Child processes continue running when the kernel instance is destroyed.

## JSON protocol

Start `jarvis-core.exe --stdio`. Each UTF-8 JSON line receives one response line;
stdout contains protocol messages, diagnostics go to stderr. A malformed request
does not terminate the session. Requests are limited to 1 MiB.

```json
{"id":"snapshot-1","method":"system_snapshot","params":{"checks":["cpu","memory","disk","system"],"top_processes":5}}
```

Every response includes `protocol_version`, `id`, `ok`, `timestamp_utc`,
`elapsed_ms`, `result` and `error`. `--request JSON` handles a single request and
returns exit code 0 for success, 2 for a command/protocol error. Startup failures
return 1. `capabilities` exposes the authoritative parameter schemas.
`ok: true` means the command was handled; check each metric section's `available`
flag and snapshot `partial` before interpreting measurements.

Snapshot checks: `cpu`, `memory`, `disk`, `network`, `processes`, `battery`,
`startup`, `system`. Default: CPU, memory, disks, system. Sampling probes run
concurrently with a nominal 300 ms sample window. Actual CPU/process sample
durations are returned. `partial: true` marks a failed section; missing samples
are not converted into healthy zero measurements.
Network rates use the measured per-adapter interval, also returned as
`sample_window_ms`; unavailable counters remain null. Unknown battery/AC state
is represented explicitly.

Memory is reported in bytes. Disk fields inherited as `_gb` use 1024³ bytes
(GiB). Commit charge is reported separately and is not pagefile occupancy.
Process CPU is normalized across logical CPUs; its memory values are working
sets, not exclusive private memory. Protected processes can be inaccessible.
On machines with multiple processor groups the CPU probe explicitly reports
`scope: calling_processor_group`. Autostart enumeration covers the classic
registry Run keys only. Diagnostics are threshold rules, not proof of a slowdown
cause. Network/OS/disk probe details are described in the provenance notes.
OS build and display version are separate fields; `product_name_registry` is raw
registry metadata, not an asserted current Windows edition. Boot time is marked
as estimated from the current clock and uptime.

## DLL API

See [include/jarvis/c_api.h](include/jarvis/c_api.h). Use `jarvis_create`,
`jarvis_execute`, `jarvis_free_string`, `jarvis_destroy`. The DLL returns owned
UTF-8 JSON; release each returned pointer with `jarvis_free_string`. Configuration
is immutable after creation. Requests on one instance are serialized. Destroy an
instance only after all its calls finish. Invalid configuration returns a null
handle. The ctypes example contains the required argument/return declarations.

## Next stage

The Python controller will expose enabled capabilities to an agent, pass tool
requests to the native kernel, collect results, and send selected context through
OpenRouter. Speech recognition and TTS follow that integration. This repository
does not yet call a model, listen to the microphone or synthesize speech.

Development proceeds through working features; Python syntax is explained as it
appears in the integration work. Stage 1 implementation is provided, not assigned
as introductory homework.
