// Adapted from evo-wnd system_doctor. See docs/PROVENANCE.md.
#include "disk_probe.h"

#include "probe_utils.h"

#include <windows.h>

namespace jarvis::probes {

nlohmann::json CollectDiskMetrics() {
    nlohmann::json volumes = nlohmann::json::array();
    nlohmann::json low_space_volumes = nlohmann::json::array();

    const DWORD drives_mask = GetLogicalDrives();
    if (!drives_mask) return {{"available", false}, {"error", "logical_drives_failed"}, {"native_code", GetLastError()}};
    for (int i = 0; i < 26; ++i) {
        if (!(drives_mask & (1u << i))) {
            continue;
        }
        const wchar_t drive_letter = static_cast<wchar_t>(L'A' + i);
        const std::wstring root = std::wstring(1, drive_letter) + L":\\";

        const UINT type = GetDriveTypeW(root.c_str());
        if (type == DRIVE_UNKNOWN || type == DRIVE_NO_ROOT_DIR || type == DRIVE_CDROM ||
            type == DRIVE_REMOTE) {
            continue;
        }

        ULARGE_INTEGER free_avail{};
        ULARGE_INTEGER total_bytes{};
        ULARGE_INTEGER total_free{};
        if (!GetDiskFreeSpaceExW(root.c_str(), &free_avail, &total_bytes, &total_free)) {
            continue;  // drive not ready (e.g. empty card reader slot)
        }

        wchar_t label[MAX_PATH + 1] = {};
        wchar_t file_system[MAX_PATH + 1] = {};
        GetVolumeInformationW(root.c_str(), label, MAX_PATH, nullptr, nullptr, nullptr, file_system,
                               MAX_PATH);
        // A failure here just leaves label/file_system empty — disk space is
        // the important part and is already known at this point.

        constexpr double kBytesPerGb = 1024.0 * 1024.0 * 1024.0;
        const double total_gb = static_cast<double>(total_bytes.QuadPart) / kBytesPerGb;
        const double free_gb = static_cast<double>(total_free.QuadPart) / kBytesPerGb;
        const double used_percent = total_gb > 0.0 ? 100.0 * (total_gb - free_gb) / total_gb : 0.0;

        const std::string drive = WideToUtf8(std::wstring(1, drive_letter) + L":");

        volumes.push_back({
            {"drive", drive},
            {"label", WideToUtf8(label)},
            {"total_gb", total_gb},
            {"free_gb", free_gb},
            {"used_percent", used_percent},
            {"file_system", WideToUtf8(file_system)},
        });

        if (free_gb < 10.0 || used_percent > 90.0) {
            low_space_volumes.push_back(drive);
        }
    }

    wchar_t system_drive_buf[16] = {};
    GetEnvironmentVariableW(L"SystemDrive", system_drive_buf, 16);

    return {
        {"system_drive", WideToUtf8(system_drive_buf)},
        {"volumes", volumes},
        {"low_space_volumes", low_space_volumes},
    };
}

}  // namespace jarvis::probes
