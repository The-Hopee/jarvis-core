// Adapted from evo-wnd system_doctor. See docs/PROVENANCE.md.
#include "startup_probe.h"

#include "probe_utils.h"

#include <windows.h>

#include <string>

namespace jarvis::probes {
namespace {

struct RunKey {
    HKEY root;
    const wchar_t* subkey;
    const char* location;
};

// Scope is intentionally limited to the classic Run keys (no shell:startup
// folder scanning) — this covers the vast majority of real autostart entries.
// Not constexpr: HKEY_CURRENT_USER/HKEY_LOCAL_MACHINE expand to an
// integer-to-pointer cast, which MSVC rejects in a constant expression.
const RunKey kRunKeys[] = {
    {HKEY_CURRENT_USER, L"Software\\Microsoft\\Windows\\CurrentVersion\\Run", "HKCU\\Run"},
    {HKEY_LOCAL_MACHINE, L"Software\\Microsoft\\Windows\\CurrentVersion\\Run", "HKLM\\Run"},
    {HKEY_LOCAL_MACHINE, L"Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run",
     "HKLM\\WOW6432Node\\Run"},
};

}  // namespace

nlohmann::json CollectStartupMetrics() {
    nlohmann::json items = nlohmann::json::array();
    int count = 0;

    for (const auto& key_info : kRunKeys) {
        HKEY key = nullptr;
        if (RegOpenKeyExW(key_info.root, key_info.subkey, 0, KEY_READ, &key) != ERROR_SUCCESS) {
            continue;  // key absent on this machine — not an error
        }

        DWORD index = 0;
        for (;;) {
            wchar_t name_buf[256];
            BYTE data_buf[4096];
            DWORD name_len = 256;
            DWORD data_len = sizeof(data_buf);
            DWORD type = 0;

            const LONG status =
                RegEnumValueW(key, index, name_buf, &name_len, nullptr, &type, data_buf, &data_len);
            if (status == ERROR_NO_MORE_ITEMS) {
                break;
            }
            ++index;
            if (status != ERROR_SUCCESS) {
                continue;  // e.g. value too large for data_buf — skip, keep enumerating
            }
            if (type != REG_SZ && type != REG_EXPAND_SZ) {
                continue;
            }

            std::wstring command(reinterpret_cast<wchar_t*>(data_buf), data_len / sizeof(wchar_t));
            const size_t nul_pos = command.find(L'\0');
            if (nul_pos != std::wstring::npos) {
                command.resize(nul_pos);
            }

            items.push_back({
                {"name", WideToUtf8(std::wstring(name_buf, name_len))},
                {"command", WideToUtf8(command)},
                {"location", key_info.location},
            });
            ++count;
        }

        RegCloseKey(key);
    }

    return {{"count", count}, {"items", items}};
}

}  // namespace jarvis::probes
