// Adapted from evo-wnd system_doctor. See docs/PROVENANCE.md.
#include "network_probe.h"

// WIN32_LEAN_AND_MEAN keeps windows.h from pulling in the legacy winsock.h,
// which would otherwise conflict with winsock2.h below. windows.h still sets
// the SDK version macros (NTDDI_VERSION) that iphlpapi.h/netioapi.h need in
// order to declare MIB_IF_ROW2/GetIfEntry2 — without it those declarations
// are silently skipped and the file fails to compile.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <winsock2.h>
#include <ws2tcpip.h>

#include <iphlpapi.h>
#include <netioapi.h>

#include "probe_utils.h"

#include <chrono>
#include <string>
#include <vector>

namespace jarvis::probes {
namespace {

std::string FormatIpv4(const SOCKADDR* sa) {
    if (sa == nullptr || sa->sa_family != AF_INET) {
        return {};
    }
    const auto* sin = reinterpret_cast<const sockaddr_in*>(sa);
    const auto& b = sin->sin_addr.S_un.S_un_b;
    char buf[16];
    sprintf_s(buf, "%u.%u.%u.%u", b.s_b1, b.s_b2, b.s_b3, b.s_b4);
    return std::string(buf);
}

struct AdapterInfo {
    NET_LUID luid{};
    std::wstring name;
    bool up = false;
    std::string ipv4;
};

}  // namespace

nlohmann::json CollectNetworkMetrics() {
    ULONG size = 15000;
    std::vector<BYTE> buffer(size);
    auto* addrs = reinterpret_cast<IP_ADAPTER_ADDRESSES*>(buffer.data());
    const ULONG flags = GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST;

    DWORD result = GetAdaptersAddresses(AF_INET, flags, nullptr, addrs, &size);
    if (result == ERROR_BUFFER_OVERFLOW) {
        buffer.resize(size);
        addrs = reinterpret_cast<IP_ADAPTER_ADDRESSES*>(buffer.data());
        result = GetAdaptersAddresses(AF_INET, flags, nullptr, addrs, &size);
    }
    if (result != NO_ERROR) {
        return {{"available", false}, {"error", "get_adapters_addresses_failed"}};
    }

    std::vector<AdapterInfo> adapters;
    for (IP_ADAPTER_ADDRESSES* p = addrs; p != nullptr; p = p->Next) {
        if (p->IfType == IF_TYPE_SOFTWARE_LOOPBACK) {
            continue;
        }
        AdapterInfo info;
        info.luid = p->Luid;
        info.name = p->FriendlyName != nullptr ? p->FriendlyName : L"";
        info.up = (p->OperStatus == IfOperStatusUp);
        for (IP_ADAPTER_UNICAST_ADDRESS* ua = p->FirstUnicastAddress; ua != nullptr; ua = ua->Next) {
            const std::string ip = FormatIpv4(ua->Address.lpSockaddr);
            if (!ip.empty()) {
                info.ipv4 = ip;
                break;
            }
        }
        adapters.push_back(info);
    }

    std::vector<MIB_IF_ROW2> samples_before(adapters.size());
    std::vector<bool> sample_before_ok(adapters.size(), false);
    std::vector<std::chrono::steady_clock::time_point> sampled_at(adapters.size());
    for (size_t i = 0; i < adapters.size(); ++i) {
        MIB_IF_ROW2 row{};
        row.InterfaceLuid = adapters[i].luid;
        sample_before_ok[i] = (GetIfEntry2(&row) == NO_ERROR);
        samples_before[i] = row;
        sampled_at[i] = std::chrono::steady_clock::now();
    }

    Sleep(kDeltaSampleIntervalMs);

    nlohmann::json result_adapters = nlohmann::json::array();
    for (size_t i = 0; i < adapters.size(); ++i) {
        MIB_IF_ROW2 row{};
        row.InterfaceLuid = adapters[i].luid;
        const bool sample_after_ok = (GetIfEntry2(&row) == NO_ERROR);
        const double interval_sec = std::chrono::duration<double>(std::chrono::steady_clock::now()-sampled_at[i]).count();

        nlohmann::json entry = {
            {"name", WideToUtf8(adapters[i].name)},
            {"status", adapters[i].up ? "up" : "down"},
            {"ipv4", adapters[i].ipv4.empty() ? nlohmann::json(nullptr) : nlohmann::json(adapters[i].ipv4)},
        };

        const bool counters_valid = sample_before_ok[i] && sample_after_ok && interval_sec > 0.0 &&
                                    row.OutOctets >= samples_before[i].OutOctets &&
                                    row.InOctets >= samples_before[i].InOctets &&
                                    row.InErrors >= samples_before[i].InErrors &&
                                    row.OutErrors >= samples_before[i].OutErrors;
        entry["sample_window_ms"] = interval_sec * 1000.0;
        if (counters_valid) {
            entry["bytes_sent_per_sec"] =
                static_cast<double>(row.OutOctets - samples_before[i].OutOctets) / interval_sec;
            entry["bytes_recv_per_sec"] =
                static_cast<double>(row.InOctets - samples_before[i].InOctets) / interval_sec;
            entry["errors_in"] =
                static_cast<long long>(row.InErrors - samples_before[i].InErrors);
            entry["errors_out"] =
                static_cast<long long>(row.OutErrors - samples_before[i].OutErrors);
        } else {
            entry["bytes_sent_per_sec"] = nullptr;
            entry["bytes_recv_per_sec"] = nullptr;
            entry["errors_in"] = nullptr;
            entry["errors_out"] = nullptr;
        }

        result_adapters.push_back(entry);
    }

    return {{"adapters", result_adapters}};
}

}  // namespace jarvis::probes
