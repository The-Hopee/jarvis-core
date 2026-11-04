// Adapted from evo-wnd system_doctor. See docs/PROVENANCE.md.
#include "system_probe.h"

#include "probe_utils.h"

#include <windows.h>

#include <ctime>

namespace jarvis::probes {

nlohmann::json CollectSystemMetrics() {
    const long long uptime_seconds = static_cast<long long>(GetTickCount64() / 1000);
    const long long now = static_cast<long long>(std::time(nullptr));
    const long long boot_time = now - uptime_seconds;

    const std::string product_name = ReadRegString(
        HKEY_LOCAL_MACHINE, L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", L"ProductName");
    const std::string build_number = ReadRegString(
        HKEY_LOCAL_MACHINE, L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", L"CurrentBuildNumber");
    const std::string display_version = ReadRegString(
        HKEY_LOCAL_MACHINE, L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", L"DisplayVersion");

    // Registry ProductName can retain legacy branding after Windows upgrades.
    // Keep it as explicitly named raw metadata instead of asserting an OS edition.
    std::string os_version = "Windows";
    if (!build_number.empty()) {
        os_version += " (Build " + build_number;
        if (!display_version.empty()) {
            os_version += ", " + display_version;
        }
        os_version += ")";
    }

    return {
        {"uptime_seconds", uptime_seconds},
        {"last_boot_time", FormatIso8601Utc(boot_time)},
        {"last_boot_time_estimated", true},
        {"os_version", os_version},
        {"product_name_registry", product_name},
        {"build_number", build_number},
        {"display_version", display_version},
    };
}

}  // namespace jarvis::probes
