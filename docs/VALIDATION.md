# Stage 1 validation

Validated locally on Windows x64, 2026-11-04 (Europe/Moscow).

- Visual Studio 2022 / MSVC 19.44, Windows SDK 10.0.26100.0.
- CMake Release build produced `jarvis-core.exe` and `jarvis_core.dll`.
- CTest `native_contract` runs six Python unittest scenarios, all passing.
- Read-only subprocess and ctypes examples both received real native CPU/RAM/OS
  measurements; sample JSON was inspected locally and is not committed.

The six integration scenarios exercise:

1. Recovery from malformed JSON and wrong root type; UTF-8 request-ID round-trip.
2. Unknown commands/fields, wrong types, integer bounds, capability schema and
   startup action gating.
3. Oversized input rejection and the next request on the same session.
4. All eight metric sections; RAM byte reconciliation, CPU bounds/sample window,
   bounded process lists, window enumeration and audio read/error reporting.
5. Registered-app enforcement and rejection of foreign PIDs. A hidden dedicated
   test executable is launched and terminated through retained ownership. No
   existing user application is terminated. Invalid volume input is rejected
   before touching audio state.
6. DLL initialization, repeated calls with explicit native string release,
   native snapshot collection and handle destruction.

Volume/mute changes and successful foreground switching are implemented but
have not been exercised against the user's interactive desktop. Foreground
activation can be denied by Windows; the kernel reports that outcome. App
creation is tested with the dedicated fixture; readiness of arbitrary third-party
application UIs is outside this stage's verification.

OpenRouter, speech recognition and TTS are later stages and are not claimed as
implemented or validated here.
