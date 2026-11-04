// Adapted from evo-wnd system_doctor. See docs/PROVENANCE.md.
#pragma once

#include <windows.h>

#include <string>

namespace jarvis::probes {

// Common wait window used by every probe that needs two samples to compute a
// delta (CPU load, per-process CPU time, network throughput). Probes that
// need a delta run this sleep on their own thread; the orchestrator launches
// them concurrently so the wait windows overlap instead of stacking up.
constexpr DWORD kDeltaSampleIntervalMs = 300;

std::wstring Utf8ToWide(const std::string& text);
std::string WideToUtf8(const std::wstring& text);

// ISO-8601 UTC timestamp, e.g. "2026-06-30T08:00:00Z".
std::string FormatIso8601Utc(long long unix_seconds);

// Reads a single REG_SZ/REG_EXPAND_SZ value. Returns empty string if the key
// or value does not exist instead of throwing.
std::string ReadRegString(HKEY root, const wchar_t* subkey, const wchar_t* value);

}  // namespace jarvis::probes
