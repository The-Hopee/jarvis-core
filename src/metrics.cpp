#include "internal.hpp"
#include "probes/cpu_probe.h"
#include "probes/memory_probe.h"
#include "probes/disk_probe.h"
#include "probes/network_probe.h"
#include "probes/process_probe.h"
#include "probes/battery_probe.h"
#include "probes/startup_probe.h"
#include "probes/system_probe.h"
#include "slowdown_rules.h"
#include <future>
#include <set>
namespace jarvis {
Json collect_snapshot(const Json& params) {
    keys(params,{"checks","top_processes"});
    const int top=integer(params,"top_processes",10,1,100);
    const std::set<std::string> valid={"cpu","memory","disk","network","processes","battery","startup","system"};
    std::set<std::string> checks={"cpu","memory","disk","system"};
    if (params.contains("checks")) {
        if (!params["checks"].is_array() || params["checks"].empty() || params["checks"].size()>8)
            throw Failure("invalid_argument","checks must be a nonempty array of at most 8 names");
        checks.clear();
        for (const auto& name:params["checks"]) {
            if (!name.is_string() || !valid.count(name.get<std::string>())) throw Failure("invalid_argument","Unknown metric check");
            checks.insert(name.get<std::string>());
        }
    }
    std::map<std::string,std::future<Json>> jobs;
    for (const auto& name:checks) jobs.emplace(name,std::async(std::launch::async,[name,top]() -> Json {
        try {
            if (name=="cpu") return probes::CollectCpuMetrics();
            if (name=="memory") return probes::CollectMemoryMetrics();
            if (name=="disk") return probes::CollectDiskMetrics();
            if (name=="network") return probes::CollectNetworkMetrics();
            if (name=="processes") return probes::CollectProcessMetrics(top);
            if (name=="battery") return probes::CollectBatteryMetrics();
            if (name=="startup") return probes::CollectStartupMetrics();
            return probes::CollectSystemMetrics();
        } catch (const std::exception& e) { return {{"available",false},{"error",e.what()}}; }
    }));
    Json sections=Json::object(); bool partial=false;
    for (auto& [name,job]:jobs) { auto result=job.get(); if (!result.contains("available")) result["available"]=!result.contains("error");
        if (!result.value("available",false)) partial=true; sections[name]=std::move(result); }
    return {{"metrics",sections},{"partial",partial},{"diagnostics",EvaluateRules(sections)}};
}
}
