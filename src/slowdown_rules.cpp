// Adapted from evo-wnd system_doctor. See docs/PROVENANCE.md.
#include "slowdown_rules.h"

#include <iomanip>
#include <sstream>
#include <string>

namespace jarvis {
namespace {

constexpr double kMemoryHighPercent = 85.0;
// The free-space/percent-used threshold that populates disk.low_space_volumes
// is applied in disk_probe.cpp; this rule only decides issue severity.
constexpr double kDiskCriticalPercent = 90.0;
constexpr double kCpuHighPercent = 80.0;
constexpr double kProcessHeavyPercent = 40.0;
constexpr int kStartupTooMany = 15;
constexpr long long kUptimeStaleSeconds = 7LL * 24 * 3600;  // 7 days
constexpr int kBatteryLowPercent = 20;

std::string FormatNumber(double value, int decimals) {
    std::ostringstream oss;
    oss << std::fixed << std::setprecision(decimals) << value;
    return oss.str();
}

// A probe section is usable for rules only if it was collected (present in
// checks[]) and did not fail (no "error" field, see each probe's WinAPI
// failure path).
bool HasOkSection(const nlohmann::json& metrics, const char* key) {
    return metrics.contains(key) && metrics[key].is_object() && !metrics[key].contains("error");
}

void AddIssue(nlohmann::json& issues, const std::string& area, const std::string& severity,
              const std::string& code, const std::string& message) {
    issues.push_back({
        {"area", area},
        {"severity", severity},
        {"code", code},
        {"message", message},
    });
}

void AddInsight(nlohmann::json& insights, const std::string& area, const std::string& text) {
    insights.push_back({{"area", area}, {"text", text}});
}

void AddRecommendation(nlohmann::json& recommendations, const std::string& text,
                       const std::string& related_area) {
    recommendations.push_back({{"text", text}, {"related_area", related_area}});
}

void EvaluateMemoryRule(const nlohmann::json& metrics, nlohmann::json& issues,
                        nlohmann::json& recommendations) {
    if (!HasOkSection(metrics, "memory")) {
        return;
    }
    const double usage = metrics["memory"].value("usage_percent", 0.0);
    if (usage > kMemoryHighPercent) {
        AddIssue(issues, "memory", "warning", "ram_high",
                 "Оперативная память загружена на " + FormatNumber(usage, 0) + "%");
        AddRecommendation(recommendations, "Закройте неиспользуемые приложения или перезагрузите компьютер",
                          "memory");
    }
}

void EvaluateDiskRule(const nlohmann::json& metrics, nlohmann::json& issues,
                     nlohmann::json& recommendations) {
    if (!HasOkSection(metrics, "disk")) {
        return;
    }
    const auto& disk = metrics["disk"];
    const auto low_space = disk.value("low_space_volumes", nlohmann::json::array());
    const auto volumes = disk.value("volumes", nlohmann::json::array());

    for (const auto& drive_json : low_space) {
        if (!drive_json.is_string()) {
            continue;
        }
        const std::string drive = drive_json.get<std::string>();

        double used_percent = 0.0;
        double free_gb = 0.0;
        for (const auto& volume : volumes) {
            if (volume.value("drive", "") == drive) {
                used_percent = volume.value("used_percent", 0.0);
                free_gb = volume.value("free_gb", 0.0);
                break;
            }
        }

        const std::string severity = used_percent > kDiskCriticalPercent ? "critical" : "warning";
        const std::string message = "На диске " + drive + " заканчивается место (" +
                                    FormatNumber(free_gb, 1) + " GB свободно, занято " +
                                    FormatNumber(used_percent, 0) + "%)";
        AddIssue(issues, "disk", severity, "disk_low_space", message);
        AddRecommendation(recommendations, "Освободите место на диске " + drive, "disk");
    }
}

void EvaluateCpuProcessRule(const nlohmann::json& metrics, nlohmann::json& insights,
                            nlohmann::json& recommendations) {
    if (!HasOkSection(metrics, "cpu") || !HasOkSection(metrics, "processes")) {
        return;
    }
    if (metrics["cpu"].value("usage_percent", 0.0) <= kCpuHighPercent) {
        return;
    }
    const auto top_by_cpu = metrics["processes"].value("top_by_cpu", nlohmann::json::array());
    for (const auto& proc : top_by_cpu) {
        if (proc.contains("cpu_percent") && proc["cpu_percent"].is_number() && proc["cpu_percent"].get<double>() > kProcessHeavyPercent) {
            const std::string proc_name = proc.value("name", std::string());
            AddInsight(insights, "processes",
                      "Процесс " + proc_name + " активно нагружает процессор");
            AddRecommendation(recommendations, "Закройте процесс " + proc_name +
                            " или обновите его, если доступна новая версия", "processes");
            break;  // the single heaviest offender is enough
        }
    }
}

void EvaluateStartupRule(const nlohmann::json& metrics, nlohmann::json& insights,
                         nlohmann::json& recommendations) {
    if (!HasOkSection(metrics, "startup")) {
        return;
    }
    if (metrics["startup"].value("count", 0) > kStartupTooMany) {
        AddInsight(insights, "startup", "Много программ в автозагрузке — это может замедлять запуск Windows");
        AddRecommendation(recommendations, "Отключите неиспользуемые программы в автозагрузке", "startup");
    }
}

void EvaluateUptimeRule(const nlohmann::json& metrics, nlohmann::json& insights,
                       nlohmann::json& recommendations) {
    if (!HasOkSection(metrics, "system")) {
        return;
    }
    if (metrics["system"].value("uptime_seconds", 0LL) > kUptimeStaleSeconds) {
        AddInsight(insights, "system", "Компьютер давно не перезагружался");
        AddRecommendation(recommendations, "Перезагрузите компьютер, чтобы применить обновления и освободить память",
                          "system");
    }
}

void EvaluateBatteryRule(const nlohmann::json& metrics, nlohmann::json& issues,
                         nlohmann::json& recommendations) {
    if (!HasOkSection(metrics, "battery")) {
        return;
    }
    const auto& battery = metrics["battery"];
    if (!battery.value("present", false)) {
        return;
    }
    if (!battery.contains("on_ac") || !battery["on_ac"].is_boolean()) return;
    const bool on_ac = battery["on_ac"].get<bool>();
    const nlohmann::json percent_field = battery.value("percent", nlohmann::json(100));
    if (!percent_field.is_number()) {
        return;  // unknown battery level (255) — nothing to warn about
    }
    const int percent = percent_field.get<int>();
    if (percent < kBatteryLowPercent && !on_ac) {
        AddIssue(issues, "battery", "warning", "battery_low",
                "Заряд батареи ниже " + std::to_string(kBatteryLowPercent) + "% и питание от сети не подключено");
        AddRecommendation(recommendations, "Подключите зарядное устройство", "battery");
    }
}

}  // namespace

nlohmann::json EvaluateRules(const nlohmann::json& metrics) {
    nlohmann::json issues = nlohmann::json::array();
    nlohmann::json insights = nlohmann::json::array();
    nlohmann::json recommendations = nlohmann::json::array();

    EvaluateMemoryRule(metrics, issues, recommendations);
    EvaluateDiskRule(metrics, issues, recommendations);
    EvaluateCpuProcessRule(metrics, insights, recommendations);
    EvaluateStartupRule(metrics, insights, recommendations);
    EvaluateUptimeRule(metrics, insights, recommendations);
    EvaluateBatteryRule(metrics, issues, recommendations);

    return {
        {"issues", issues},
        {"insights", insights},
        {"recommendations", recommendations},
    };
}

}  // namespace jarvis
