// Adapted from evo-wnd system_doctor. See docs/PROVENANCE.md.
#include "battery_probe.h"

#include <windows.h>

namespace jarvis::probes {

nlohmann::json CollectBatteryMetrics() {
    SYSTEM_POWER_STATUS sps{};
    if (!GetSystemPowerStatus(&sps)) {
        return {{"available", false}, {"error", "get_system_power_status_failed"}};
    }

    if (sps.BatteryFlag == 255) return {{"available", false}, {"error", "battery_status_unknown"}};

    const bool present = !(sps.BatteryFlag & BATTERY_FLAG_NO_BATTERY);
    if (!present) {
        return {{"present", false}};
    }

    const nlohmann::json percent = (sps.BatteryLifePercent == 255)
        ? nlohmann::json(nullptr)
        : nlohmann::json(static_cast<int>(sps.BatteryLifePercent));
    const bool charging = (sps.BatteryFlag & BATTERY_FLAG_CHARGING) != 0;
    const nlohmann::json on_ac = sps.ACLineStatus == 255 ? nlohmann::json(nullptr) : nlohmann::json(sps.ACLineStatus == 1);
    const bool power_saving = (sps.SystemStatusFlag == 1);

    return {
        {"present", true},
        {"percent", percent},
        {"charging", charging},
        {"on_ac", on_ac},
        {"power_saving", power_saving},
    };
}

}  // namespace jarvis::probes
