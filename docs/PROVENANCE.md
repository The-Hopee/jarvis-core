# Origin and adaptation

Reviewed local project: Rikor `evo-wnd`, clean worktree at revision
`94fc440acf2b94c5ddc68887eaed9f3132705a6d`.

Adapted files: `lib/src/modules/system_doctor/engine/probes/*.{h,cpp}` and
`slowdown_rules.{h,cpp}`. Original paths and SHA-256 hashes are preserved in
`source_manifest.json`. The project-specific runtime/UI/DLL framework and its
configuration were not imported. Source project files have not been modified.

The `command_center` window snapshot/list/launcher implementations were reviewed
for the separation between command dispatch and Windows operations. Window,
audio and managed-process actions here are standalone implementations under the
Jarvis protocol, with no dependency on the original runtime.

Changes made while adapting:

- Namespace changed to `jarvis`; a standalone CMake build, JSON-line CLI and C ABI
  DLL were added.
- UTF conversion uses explicit source lengths and correctly sized output
  buffers; invalid UTF-8 and embedded NUL arguments are rejected.
- CPU sampling now uses GetSystemTimes and measured duration, exposing unavailable
  samples and processor-group scope instead of substituting zero on PDH errors.
- Process sampling uses retained RAII handles, actual elapsed intervals and null
  values when a sample is unavailable. Top lists are bounded.
- Memory exposes byte counts and system commit from GetPerformanceInfo; commit
  charge is not described as pagefile usage.
- Snapshot probes execute in parallel; exceptions are contained per probe.
  Rules skip absent/failed sections and unavailable process CPU values.
- Network rates use actual measured per-adapter intervals; unknown battery/AC
  status is explicit, and failure to enumerate logical drives is reported.
- OS build/display version are exposed separately from the raw registry product
  label; boot time is explicitly marked as an estimate.
- Original disk, battery, network, startup and OS probes supply the remaining
  Windows-specific collection logic; their limits are documented in the README.
- Mutations are gated at startup; launch requests resolve registered executable
  IDs, and process termination is limited to retained child handles.

The repository is private. No project-wide open-source license is asserted for
the adapted source. nlohmann/json is a separate MIT-licensed build dependency;
its license remains in its fetched source tree at the pinned revision.
