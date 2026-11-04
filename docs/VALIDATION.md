# Validation

## Version 0.3 update

2026-11-04: 39 Python tests and eight native contract scenarios pass.

- Real YouTube HTML search returned video IDs/titles for the requested artist.
  The exact reported utterance was executed through the CLI and opened a concrete
  watch URL, with the selected title spoken by the response formatter.
- Parser tests cover classic/new YouTube result formats, ad exclusion and refusal
  to invent a video when a challenge page replaces results.
- Real Chromium exercised a local VK messenger fixture: recipient selection,
  outgoing/incoming context, send button, appearance of an outgoing message, and
  suppression of a duplicate send without leaving another draft.
- Message tests cover ambiguous identities, inflected Russian names, direct-user
  send intent, explicit draft-only requests, operation receipts, uncertain
  delivery reporting and style extraction from outgoing messages only.
- Two coding workers ran concurrently in real separate Git worktrees on a test
  repository, produced real commits, merged into an integration branch and
  passed a check importing both modules. The original checkout/HEAD stayed
  unchanged. Model responses in this test were fixtures, not live LLM inference.
- Native Telegram link tests reject arbitrary schemas, embedded query arguments,
  invalid identifiers and disabled actions before launching anything.
- Official Silero v5 Russian model synthesized nonempty WAVs for Aidar and
  Eugene, including mixed Russian/Latin/numeric text. Local speech playback
  completed. User selected Eugene; samples are kept outside Git.
- Telegram account credentials/session and VK login are deferred by the user.
  Real private chats were not read and no real messages were sent during tests.
  A public VK navigation reached its login page; authenticated selectors await
  validation after the user signs in.
- Live OpenRouter request still returns HTTP 401. Contextual replies and coding
  jobs have implemented protocol paths but are not claimed as live-model tested.

Optional voice runtime: CPU torch 2.15.0+cpu, NumPy 2.5.4, SciPy 1.18.1; local
weights are downloaded from the official Silero URL and are not committed.

## Interactive-user autostart update

2026-11-04: registered and started the owned `Jarvis-HomeAssistant` Task Scheduler
task for the current account, Interactive/Limited, 10-second logon delay,
`pythonw.exe -m jarvis.background`, IgnoreNew, no execution time limit and three
failure restarts at one-minute intervals. Existing trading-bot tasks were only
inspected; their registrations and disabled states were not changed.

- Four additional Python tests pass: process-level singleton exclusion, recovery
  after a crashed owner, named-event shutdown with handle cleanup, and UTF-8
  partial-line logging. Combined Python suite: 26 tests.
- Live scheduled start reached the microphone-listening log entry without a
  console window. Graceful stop and restart returned the task to a running state.
  A duplicate foreground voice launch was rejected without opening a second mic.
- The logon trigger/settings were inspected; an actual Windows logoff/logon was
  not forced during this session. Failure restart settings are registered; the
  live assistant was not deliberately crashed to test Task Scheduler recovery.
- A real OpenRouter request was attempted after a key appeared in `.env`.
  OpenRouter returned HTTP 401. The current key is read but is not accepted;
  actual model inference still requires working credentials. Local commands
  continue through the fallback parser. No key values are printed or committed.

Run all Python tests with `python -m unittest discover -s tests -p test_*.py` from
the installed project environment. Native code is unchanged by this update.

## Stage 2: home assistant 0.2.0

Validated on 2026-11-04, Windows x64, Python 3.13.15, MSVC 19.44 / SDK 10.0.26100.0.

- Release EXE/DLL rebuilt successfully. Native contract suite now contains seven
  scenarios, all passing, including rejection of non-web URLs without opening them.
- 22 Python tests pass. They cover tool schemas, OpenRouter request/result
  correlation, bounded tool iterations, duplicate action suppression, error
  fallback without replay, literal .env parsing, URL handling, wake-word expiry,
  explicit location precision, weather caching and map-search outage fallback.
- Real IPC tests use one persistent native process from six caller threads,
  verify distinct request IDs, recover after a command error, and close correctly
  after a child crash or an actual timeout. Only each test's own child is killed.
- A local HTTP fixture using the OpenRouter chat-completion schema requests a
  tool, reaches real C++ CPU/RAM measurements, receives the correlated tool result,
  and returns a final assistant message. This is a protocol integration test,
  not a request to an actual language model.
- Edge synthesized a nonempty MP3 with `ru-RU-DmitryNeural`. Windows MCI playback
  completed for a short phrase and a spoken real machine-status response.
- Windows SAPI generated 16 kHz mono WAVs for four Russian command phrases;
  Vosk recognized their wake words and routed all four to the intended tools.
  One recognized inflection, «состоянии машины», was added to the fallback parser.
- The default microphone opened and captured 100 ms without overflow. This
  verifies driver access, not recognition accuracy for the user's actual voice.
- YouTube and Telegram were requested through Python -> persistent IPC -> C++.
  Windows accepted browser launch and created the registered Telegram process.
  Page loading and application UI readiness are not asserted.
- Live IP location and Open-Meteo weather calls succeeded. Windows did not
  provide coordinates; IP resolved to Stockholm, which may be a VPN/proxy exit.
  No current city is assumed from the user's timezone or account language.
- Public Overpass servers were unavailable from this environment. `find_places`
  reports `lookup_status: unavailable` and provides a Yandex Maps search URL;
  it does not invent place names. The real OSM parsing path is covered by fixtures.

Actual OpenRouter inference is **not yet verified**: the user will add their key
to local `.env` later. No paid LLM requests or microphone recordings were stored.
Speech is half-duplex; the microphone closes during tool execution and playback.
Background startup, barge-in, streaming replies and arbitrary desktop automation
are not part of version 0.2.

Reproduce the automated checks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_assistant.py -v
ctest --test-dir build -C Release --output-on-failure
```

Opt-in checks (live services / local speech synthesis):

```powershell
.\.venv\Scripts\python.exe scripts\voice_smoke.py
.\.venv\Scripts\python.exe scripts\service_smoke.py
.\.venv\Scripts\python.exe -m jarvis --doctor
```

## Stage 1: original native-kernel validation

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

The checks above describe the original stage 1 snapshot. See stage 2 for the
current Python/OpenRouter/speech implementation and its validation limits.
