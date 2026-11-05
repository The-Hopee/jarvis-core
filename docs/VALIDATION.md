# Validation

## Version 0.7 — durable background jobs

2026-11-05: **121 Python tests pass**, **9 native scenarios pass**, 0.7.0
EXE/DLL rebuilt. Queue tests exercise two concurrent workers, a queued task
cancelled before execution, late model replies after cancellation, dependencies,
failed dependencies, bounded capacity, cancellation during a resource wait,
single coding-job admission, shared VK ownership and idle microphone release.
A real owned 30-second test process was cancelled in under five seconds;
unrelated processes were not selected. Interrupted jobs are not replayed.

Silent live integration observed queued/queued → running/running →
running/completed → completed/completed using real SQLite, model and C++ probe.
Only the read-only system-status tool was exposed in that probe. Real muted
text CLI on an isolated LOCALAPPDATA profile accepted background work, printed
completion, handled a status query and exited with code zero without a traceback.

Data: [stage07-2026-11-05.json](benchmarks/stage07-2026-11-05.json).
Commands/limitations: [UPGRADE_07.md](UPGRADE_07.md). New sending code paths were
not exercised against real people. Heavy-model coding acceptance remains open.

## Version 0.6 — incremental voice and ASR comparison

2026-11-05: **111 Python tests pass**, **9 native scenarios pass**, 0.6.0
EXE/DLL rebuilt. Real MP3 packets are decoded/resampled before HTTP completion;
unit tests encode actual MP3/ID3 input and exercise split packets, partial
failure without replay, cancellation, SSE completion markers, tool-argument
buffering and concurrent span bookkeeping. Legacy nonstreaming tests remain.

32 identical synthetic files: Scribe p50/p95 1.186/1.654 s, normalized WER
1.39%; Whisper Turbo 2.524/8.134 s, WER 4.86%; local Vosk 0.575/0.712 s,
WER 6.25%. No failed calls. Scribe remains primary; Vosk is a local fallback.
This comparison is not a benchmark of live-user microphone accuracy.

Two live voice streams yielded first PCM at 2.532/1.948 s and completed network
decoding at 3.189/3.307 s, without playing audio. Real SSE+TTS passed two
simulated-output turns. A real-time replay of the system-status command reached
virtual PCM output at 4.540 s after estimated speech end, with no LLM calls.
One short physical PCM output completed with the selected voice reference A.
That physical probe had a 5.322 s cloud first-byte wait, so no general 2–5 s
promise is made. Playback markers are dispatch timings, not acoustic readings.

Aggregate: [stage06-2026-11-05.json](benchmarks/stage06-2026-11-05.json).
Usage and limitations: [UPGRADE_06.md](UPGRADE_06.md). Other account/coding/pilot
acceptance items remain open. No private messages were read or sent here.

## Version 0.5 — timings and cached progress

2026-11-05: full Python suite: **100 tests pass**, native contract: **9 scenarios
pass**. Release EXE/DLL and Python report version 0.5.0. Four short status clips
were generated with the existing chosen reference A; credentials and account
sessions were not changed. Tests cover slow/fast turns, status/final audio
serialization, stale status cancellation, a bounded MCI status wait, absent cache,
voice cache invalidation, failures, stop after synthesis, rejected tool timings,
content-free logging, rotation and estimated Vosk word-end timestamps.

32 synthetic WAVs were replayed in real time through the input pipeline with
live OpenRouter ASR/LLM/TTS. Native system probes were real; app/site/weather
actions were fixtures. No microphone or private chats were used. All 32 completed.
That baseline candidate predates the final deterministic brevity and bounded MCI
status guards; those changes received targeted automated checks and four final
live cold repetitions. The four final repetitions synthesized audio silently;
no playback-start result is claimed for them. All four completed.

Baseline warm median/p95: ASR **1.413/1.917 s**, model requests **1.437/3.393 s**,
TTS preparation **3.493/9.060 s**, estimated speech end to feedback
**1.868/2.349 s**, to answer playback **8.472/15.388 s**. These are different
stages, not additive totals. Word-end estimates and application playback dispatch
are not an acoustic measurement. Responses/conditions vary across the corpus.
Short cached feedback addresses silence; a 2–5 s substantive reply is not yet
established. The next stage targets full-file TTS buffering.

Aggregate data: [stage05-2026-11-05.json](benchmarks/stage05-2026-11-05.json).
Usage, privacy of the separate metrics file and reproduction:
[UPGRADE_05.md](UPGRADE_05.md). Existing assistant.log still logs console dialogue.
VK music playback, live VK/TG sending and live coding remain separate open checks.

## VK login redirect fix

2026-11-05: all 84 Python tests pass. The user completed VK login, but pressing
Enter triggered another vk.com/im navigation during a vk.ru callback, causing
an uncaught Playwright interruption error.

- Login confirmation now observes the completed account UI across browser tabs;
  it does not force messenger navigation after Enter. Current VK profile-menu
  and messenger-list markers are recognized, and a URL alone is not treated as
  successful authentication.
- Shared bounded navigation lets existing callbacks settle and waits for the
  redirected destination after an interrupted goto. Network/profile/window errors
  are reported as service errors with a preserved profile rather than a traceback.
- Seven new Chromium regression scenarios cover the exact redirect shape,
  interrupted navigation without replay, already-running callbacks, login in
  another tab, incomplete login, network failure and trusted URL/UI boundaries.
- The real saved profile is authenticated. The fixed --vk-login command exited
  successfully with "Сохранённый вход в VK подтверждён"; no password was entered
  by the assistant, and credentials/cookie values/private chat text were not read.
- Current VK music uses MusicTrackRow and search_audio_input rather than the
  old audio_row layout. The adapter now reads those controls and limits searches
  to AudioCatalog_SectionAllTracks, excluding personal-library/recommendation rows.
  A new Chromium fixture includes both header and music search plus an unrelated
  recommendation; it verifies the correct field, result and playback/pause/resume.
- A real authenticated search through browser IPC for the specified artist now
  returns tracks by that artist. Actual account audio playback and private-message
  sending were not performed in this fix. Messenger search is scoped away from
  the global header search; remaining authenticated conversation selectors still
  require a selected-dialog validation when requested by the user.

## VK music update

2026-11-05: all 76 Python tests pass, including 13 new music/browser cases.
Native C++ code is unchanged from the already validated 0.4 build.

- VK music search, indexed playback, pause/resume, next/previous and status are
  exposed through the existing persistent browser IPC. Separate browser pages
  keep messenger navigation from unloading the player. Long track lists are
  read in one bounded DOM snapshot rather than per-row IPC loops.
- Actual headless Chromium plays a silent fixture WAV through a detached Audio
  object. Tests verify elapsed playback time, native playing-event sequence,
  selected-row identity, pause/resume, stable indexed results, manual switching,
  and search while another song continues. Old advancing audio does not falsely
  confirm a newly selected stalled song, including on another user turn.
- Further tests reject stale/reordered/empty results, unverified playback claims,
  repeated toggle/skip actions, private stream/token data in public results,
  mixing VK track numbers with YouTube video numbers, and using media selection
  to continue an older pending outbound-message recipient choice.
- Login-required errors release the owned browser profile and preserve the typed
  IPC error so --vk-login can open the profile. A live browser request returned
  vk_login_required. A real OpenRouter turn chose play_vk_music for the requested
  VK track and reported the login requirement without a YouTube substitution.
- The user previously deferred account login. Authenticated VK selectors and
  actual tracks in the user's account remain unverified until that login.
  No private live chats were read and no real messages were sent.
- While VK music is active (or start remains uncertain), wake-free follow-up is
  disabled after normal responses. A deliberate wake alone still grants a short
  command window. Pause restores the configured conversational window. The guard
  persists through a conversation reset because that reset does not stop music.

Commands/setup: [VK_MUSIC.md](VK_MUSIC.md). The chosen voice A is unchanged.

## Version 0.4 update

2026-11-05: 63 Python tests and nine native contract scenarios pass; Release
EXE/DLL rebuilt locally. Earlier sections below describe historical snapshots.

- Live OpenRouter chat and tool use now work. The previous local key was a
  management/provisioning key. A separate inference key with a $5 total limit
  and no periodic reset was created; the original local configuration is backed
  up outside Git. No key values or private account IDs are published.
- Strict routing previously returned 404 because parallel_tool_calls=false
  excluded the current GPT-4.1-mini providers. Omitting this optional parameter
  restores the route; bounded serial execution remains in the controller.
- Real model calls launched the installed VS Code, continued discussion after
  the user's second turn without another launch, created a DOCX, and filled a
  template with synthetic name/city values. Native window enumeration confirmed
  the resulting document title in an actual ONLYOFFICE window. The initial
  semantic-field mismatch found during the live check was fixed and covered by
  a regression test; the repeated template filling succeeded.
- Document tests exercise split formatting runs, repeated placeholders, table
  and header text, content controls, preserved source hashes, namespace retention,
  all-or-nothing missing-field validation, insertion treated as literal text,
  no overwrites, bounded paths/packages and failed opening after a saved result.
- Native DOCX tests use a dedicated executable fixture, and check directory and
  extension boundaries before launching. Real minimize-all/volume mutations
  were not invoked by tests against the user's desktop.
- Conversation/audio tests cover follow-up expiry/sleep, ambiguity continuation,
  safe pronoun resolution, stable cached video ordering, dialogue memory after
  errors, immediate app launch, current-request desktop-action grants, WAV payloads,
  microphone closure before cloud use, ignored idle speech, punctuation retention,
  reference-conditioned TTS payloads and secret-free single-attempt errors.
- OpenRouter Scribe v2 actually transcribed an existing synthetic speech sample
  in about 1.6 seconds. It also transcribed/diarized a user-supplied public TikTok
  source. The 18.6 s assistant-only reference and transcript remain outside Git.
  Fish Audio s2.1-pro generated a nonempty MP3 from that reference, playback
  completed, and an independent ASR request recovered the generated Russian text.
  The user found its naturalness/background unsatisfactory; that reference was
  replaced. VSThemes blocked automatic download with HTTP 429, then the user
  supplied the downloaded archive locally. It contains 61 WAVs. Audio members
  were streamed with size/CRC checks into numbered local files; PDF/URL entries
  were not extracted or executed. Musical greetings were excluded from references.
  A 15.0 s dialogue reference and a 19.0 s narration reference produced two TTS
  previews. Both were played twice; the user selected A (dialogue). The running
  assistant now uses that reference with Fish Audio s2.1-pro through OpenRouter.
  Twelve exact response clips are configured locally, including the wake response;
  an actual CLI speech check played the original response from that manifest.
  Full-response matching, rejection of path escape, and avoiding a wrong clip
  for a longer response are covered by two additional tests.
  OpenRouter Scribe ASR is enabled.
  Cloud TTS resumes on a later turn after its one-minute error cooldown.
- Telegram/VK login remains explicitly deferred. No real private messages were
  read/sent. Coding-agent jobs with actual cloud models were not run in this update.

CLI: `--doctor`, `--speak`, `--voice-previews`, `manage.cmd foreground`.
See [UPGRADE_04.md](UPGRADE_04.md) for configuration and manual verification.

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

## 2026-11-05 — 0.8 profiles and skills

128 Python tests and the native contract suite pass. Real OpenRouter Responses tool/result round trips completed for GPT-6 Sol high and GPT-6.1 Terra low. Terra created a real DOCX using create_document, with no application launch or audio; cost $0.0026648. Routing, manual modes, opaque reasoning replay, incomplete response rejection and concurrent budget reservations are tested. ASR/TTS charges are outside the LLM budget; provider key cap is unchanged.

## 2026-11-05 — stages 0.9 through 0.11 RC

136 Python tests and all nine native contract scenarios pass locally. Live VK search/play/pause is verified with a muted browser; one own Saved Messages note persisted after reload, with a reused receipt on duplicate operation. A modern ambiguous contact search returned two candidates without opening a chat. Live Telegram is deferred by the user while my.telegram.org blocks app creation. Real weather and YouTube lookups and DOCX create/fill/source-preservation checks pass.

GPT-6 Sol high completed a source demo with two workers, checks and independent review for $0.0484112. The frozen EXE also completed a separate two-worker coding demo for $0.0233105; both kept the original checkout unchanged. Frozen runtime/doctor/control/offline command/UI checks pass after installation into a path containing Cyrillic and spaces, with empty private data and a Windows-only PATH. UTF-8 process manifests fixed the Vosk Unicode path failure. The package contains no key or personal voice. Installer unit checks cover upgrade, rollback, corruption, extra files, foreign-directory protection and actual temporary uninstall preserving personal settings.

Limits: this is the same Windows installation with isolated data, not a clean VM or the uncle PC. Actual logon autostart, uncle hardware/pilot, selected ordinary VK recipients and live Telegram remain external acceptance checks. The artifact remains a prerelease; no stable 1.0 is claimed.

## 2026-11-05 — stages 0.9 through 0.11 RC

154 Python tests and all nine native contract scenarios pass locally. Live VK search/play/pause is verified with a muted browser; one own Saved Messages note persisted after reload, with a reused receipt on duplicate operation. A modern ambiguous contact search returned two candidates without opening a chat. Live Telegram is deferred by the user while my.telegram.org blocks app creation. Real weather and YouTube lookups and DOCX create/fill/source-preservation checks pass.

GPT-6 Sol high completed a source demo with two workers, checks and independent review for $0.0484112. The final frozen EXE also completed a separate two-worker coding demo for $0.033351; both kept the original checkout unchanged. Frozen runtime/doctor/control/offline command/UI checks pass after installation into a path containing Cyrillic and spaces, with empty private data and a Windows-only PATH. UTF-8 process manifests fixed the Vosk Unicode path failure. The package contains no key or personal voice. Installer unit checks cover upgrade, rollback, corruption, extra files, foreign-directory protection and actual temporary uninstall preserving personal settings.

Limits: this is the same Windows installation with isolated data, not a clean VM or the uncle PC. Actual logon autostart, uncle hardware/pilot, selected ordinary VK recipients and live Telegram remain external acceptance checks. The artifact remains a prerelease; no stable 1.0 is claimed.

Privacy update requested by the owner: local dictation, no chat context to cloud AI. 154 tests include private direct/background/error/status paths, freeform dictation, credentials, explicit project selection, private TTS, ASR rejection, redirect/origin restrictions, UTF-8 browser-worker IPC and a real Chromium canary fetch blocked before transport. The offline privacy-check command uses synthetic accounts and fake transports. A real own VK note through the protected browser/IPC path reached zero cloud model calls and was absent from subsequent model history. Public Sol/Terra tool rounds and a light-model greeting work with ZDR/data_collection=deny. Six logical coding tasks are executed in bounded two-worker waves in the Git integration test. This module is not an OS firewall/sandbox; untrusted code still requires separate isolation.

## Build compatibility follow-up after the RC tag

The first independent Windows CI build selected MSVC 14.51 and failed with STL1011:
the SDK's C++/WinRT headers selected deprecated experimental coroutines in C++17.
Main now builds as C++20, using standard coroutine support, consistent with
[Microsoft's C++/WinRT update](https://github.com/microsoft/cppwinrt/discussions/1580).
The local MSVC 19.44 rebuild and all nine native contract scenarios pass.
The published RC ZIP remains the original verified MSVC 19.44 build and its SHA256;
this build configuration follow-up does not replace any published asset.

The next CI build and all 154 Python tests passed. Native document validation
then exposed a test-only short-path alias assumption (`RUNNER~1` versus
`runneradmin`). The test now compares actual file identity with `samefile`,
retains its root/type checks, and always stops its own test child in `finally`.

The following independent run passed both suites, packaging, and every frozen
runtime check, but its report write failed because the fresh account had no
`Jarvis/benchmarks` directory. The developer smoke script now creates that output
directory before writing. This changes the report exporter, not the shipped EXE.

## Independent Windows CI — complete

[Run 42089775592](https://github.com/The-Hopee/jarvis-core/actions/runs/42089775592)
completed successfully for main commit `f90aa0d`: dependency installation, MSVC
C++20 build, 154 Python tests, all nine native scenarios, PyInstaller packaging,
all frozen runtime/UI/privacy checks in an isolated Cyrillic profile, and artifact
upload. This separately built CI artifact does not replace the published RC ZIP.
The owner's source installation is running through `Jarvis-HomeAssistant` again.
Another person's interactive installation and actual Windows logon remain pilot
checks, as do Telegram and selected ordinary VK recipients.
