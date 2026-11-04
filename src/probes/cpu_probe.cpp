// Reworked from evo-wnd two-sample CPU probe. See docs/PROVENANCE.md.
#include "cpu_probe.h"
#include "probe_utils.h"
#include <chrono>
namespace jarvis::probes {
namespace {
ULONGLONG ticks(const FILETIME& f) { ULARGE_INTEGER n{}; n.LowPart=f.dwLowDateTime; n.HighPart=f.dwHighDateTime; return n.QuadPart; }
}
nlohmann::json CollectCpuMetrics() {
    FILETIME idle0{},kernel0{},user0{},idle1{},kernel1{},user1{};
    if (!GetSystemTimes(&idle0,&kernel0,&user0)) return {{"available",false},{"error","get_system_times_failed"},{"native_code",GetLastError()}};
    const auto start=std::chrono::steady_clock::now(); Sleep(kDeltaSampleIntervalMs);
    if (!GetSystemTimes(&idle1,&kernel1,&user1)) return {{"available",false},{"error","get_system_times_failed"},{"native_code",GetLastError()}};
    const double elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
    if (ticks(idle1)<ticks(idle0)||ticks(kernel1)<ticks(kernel0)||ticks(user1)<ticks(user0)) return {{"available",false},{"error","cpu_counters_reset"}};
    const auto total=(ticks(kernel1)-ticks(kernel0))+(ticks(user1)-ticks(user0));
    const auto idle=ticks(idle1)-ticks(idle0);
    if (!total || idle>total) return {{"available",false},{"error","invalid_cpu_sample"}};
    return {{"available",true},{"usage_percent",100.0*static_cast<double>(total-idle)/static_cast<double>(total)},
        {"logical_processors",GetActiveProcessorCount(ALL_PROCESSOR_GROUPS)},
        {"scope",GetActiveProcessorGroupCount()>1?"calling_processor_group":"system"},{"sample_window_ms",elapsed}};
}
}
