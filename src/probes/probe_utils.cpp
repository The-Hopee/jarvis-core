// Adapted from evo-wnd system_doctor; corrected UTF buffer boundaries.
#include "probe_utils.h"
#include "../internal.hpp"
#include <ctime>
#include <vector>
namespace jarvis::probes {
std::wstring Utf8ToWide(const std::string& text) { return jarvis::wide(text); }
std::string WideToUtf8(const std::wstring& text) { return jarvis::utf8(text); }
std::string FormatIso8601Utc(long long seconds) {
    const std::time_t t=static_cast<std::time_t>(seconds);
    std::tm utc{}; gmtime_s(&utc,&t); char buffer[32]{};
    std::strftime(buffer,sizeof(buffer),"%Y-%m-%dT%H:%M:%SZ",&utc); return buffer;
}
std::string ReadRegString(HKEY root,const wchar_t* subkey,const wchar_t* value) {
    DWORD size=0;
    if (RegGetValueW(root,subkey,value,RRF_RT_REG_SZ|RRF_RT_REG_EXPAND_SZ,nullptr,nullptr,&size)!=ERROR_SUCCESS || !size) return {};
    std::vector<wchar_t> data(size/sizeof(wchar_t)+1,L'\0');
    if (RegGetValueW(root,subkey,value,RRF_RT_REG_SZ|RRF_RT_REG_EXPAND_SZ,nullptr,data.data(),&size)!=ERROR_SUCCESS) return {};
    return WideToUtf8(data.data());
}
}
