# Validation

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
