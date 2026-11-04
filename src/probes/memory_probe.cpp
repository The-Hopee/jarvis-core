// Adapted from evo-wnd; system commit is not actual pagefile usage.
#include "memory_probe.h"
#include <windows.h>
#include <psapi.h>
namespace jarvis::probes {
nlohmann::json CollectMemoryMetrics() {
    MEMORYSTATUSEX status{}; status.dwLength=sizeof(status);
    if (!GlobalMemoryStatusEx(&status)) return {{"available",false},{"error","global_memory_status_failed"},{"native_code",GetLastError()}};
    nlohmann::json result={{"available",true},{"usage_percent",status.dwMemoryLoad},
        {"physical_total_bytes",status.ullTotalPhys},{"physical_available_bytes",status.ullAvailPhys},
        {"physical_used_bytes",status.ullTotalPhys-status.ullAvailPhys}};
    PERFORMANCE_INFORMATION info{}; info.cb=sizeof(info);
    const bool ok=GetPerformanceInfo(&info,sizeof(info))!=FALSE; result["commit_available"]=ok;
    result["commit_used_bytes"]=ok?nlohmann::json(static_cast<unsigned long long>(info.CommitTotal)*info.PageSize):nlohmann::json(nullptr);
    result["commit_limit_bytes"]=ok?nlohmann::json(static_cast<unsigned long long>(info.CommitLimit)*info.PageSize):nlohmann::json(nullptr);
    return result;
}
}
