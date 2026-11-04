// Adapted from evo-wnd: RAII, actual intervals, unavailable samples stay null.
#include "process_probe.h"
#include "probe_utils.h"
#include "../internal.hpp"
#include <psapi.h>
#include <tlhelp32.h>
#include <algorithm>
#include <chrono>
#include <vector>
namespace jarvis::probes {
namespace {
ULONGLONG ticks(const FILETIME& f) { ULARGE_INTEGER n{}; n.LowPart=f.dwLowDateTime; n.HighPart=f.dwHighDateTime; return n.QuadPart; }
struct Candidate { DWORD pid; std::wstring name; jarvis::Handle handle; ULONGLONG cpu; std::chrono::steady_clock::time_point at; };
}
nlohmann::json CollectProcessMetrics(int top_n) {
    jarvis::Handle snapshot(CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0));
    if (!snapshot) return {{"available",false},{"error","toolhelp_snapshot_failed"},{"native_code",GetLastError()}};
    PROCESSENTRY32W entry{}; entry.dwSize=sizeof(entry);
    if (!Process32FirstW(snapshot.get(),&entry)) return {{"available",false},{"error","process_enumeration_failed"},{"native_code",GetLastError()}};
    std::vector<Candidate> candidates; unsigned total=0,inaccessible=0;
    do {
        if (!entry.th32ProcessID) continue; ++total;
        jarvis::Handle h(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,entry.th32ProcessID));
        FILETIME created{},exited{},kernel{},user{};
        if (!h || !GetProcessTimes(h.get(),&created,&exited,&kernel,&user)) { ++inaccessible; continue; }
        candidates.push_back({entry.th32ProcessID,entry.szExeFile,std::move(h),ticks(kernel)+ticks(user),std::chrono::steady_clock::now()});
    } while (Process32NextW(snapshot.get(),&entry));
    const DWORD enum_error=GetLastError();
    if (enum_error!=ERROR_NO_MORE_FILES) return {{"available",false},{"error","process_enumeration_incomplete"},{"native_code",enum_error}};
    const auto start=std::chrono::steady_clock::now(); Sleep(kDeltaSampleIntervalMs);
    const double cpus=static_cast<double>((std::max)(DWORD(1),GetActiveProcessorCount(ALL_PROCESSOR_GROUPS)));
    std::vector<nlohmann::json> result;
    for (auto& c:candidates) {
        FILETIME created{},exited{},kernel{},user{};
        const bool sample_ok=GetProcessTimes(c.handle.get(),&created,&exited,&kernel,&user)!=FALSE;
        const double interval=std::chrono::duration<double>(std::chrono::steady_clock::now()-c.at).count();
        nlohmann::json cpu=nullptr;
        if (sample_ok && interval>0 && ticks(kernel)+ticks(user)>=c.cpu)
            cpu=100.0*static_cast<double>(ticks(kernel)+ticks(user)-c.cpu)/(interval*10000000.0*cpus);
        PROCESS_MEMORY_COUNTERS pmc{}; bool memory_ok=K32GetProcessMemoryInfo(c.handle.get(),&pmc,sizeof(pmc))!=FALSE;
        if (!memory_ok) { jarvis::Handle h(OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,FALSE,c.pid));
            memory_ok=h && K32GetProcessMemoryInfo(h.get(),&pmc,sizeof(pmc)); }
        result.push_back({{"pid",c.pid},{"name",WideToUtf8(c.name)},{"cpu_percent",cpu},
            {"working_set_bytes",memory_ok?nlohmann::json(pmc.WorkingSetSize):nlohmann::json(nullptr)},
            {"sample_available",sample_ok},{"memory_available",memory_ok}});
    }
    auto by_cpu=result,by_memory=result;
    const auto numeric=[](const nlohmann::json& v,const char* key) { return v[key].is_number()?v[key].get<double>():-1.0; };
    std::sort(by_cpu.begin(),by_cpu.end(),[&](const auto& a,const auto& b){return numeric(a,"cpu_percent")>numeric(b,"cpu_percent");});
    std::sort(by_memory.begin(),by_memory.end(),[&](const auto& a,const auto& b){return numeric(a,"working_set_bytes")>numeric(b,"working_set_bytes");});
    const auto n=static_cast<std::size_t>((std::max)(1,(std::min)(100,top_n)));
    if (by_cpu.size()>n) by_cpu.resize(n); if (by_memory.size()>n) by_memory.resize(n);
    return {{"available",true},{"total_count",total},{"sampled_count",result.size()},{"inaccessible_count",inaccessible},
        {"sample_window_ms",std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count()},
        {"top_by_cpu",by_cpu},{"top_by_memory",by_memory}};
}
}
