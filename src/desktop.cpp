#include "internal.hpp"
#include <shellapi.h>
#include <winhttp.h>
#include <roapi.h>
#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Devices.Geolocation.h>
#include <chrono>

namespace jarvis {
Json open_web_url(const Json& params) {
    keys(params,{"url"});
    const auto input=string_value(params,"url");
    if (input.size()>4096) throw Failure("invalid_argument","URL is too long");
    const auto url=wide(input);
    for (wchar_t c:url) if (c<=32||c==127||c==L'"'||c==L'\\')
        throw Failure("invalid_argument","URL contains unsupported characters; percent-encode spaces");
    URL_COMPONENTS components{}; components.dwStructSize=sizeof(components);
    components.dwSchemeLength=components.dwHostNameLength=components.dwUserNameLength=components.dwPasswordLength=static_cast<DWORD>(-1);
    if (!WinHttpCrackUrl(url.c_str(),static_cast<DWORD>(url.size()),ICU_REJECT_USERPWD,&components) ||
        (components.nScheme!=INTERNET_SCHEME_HTTP&&components.nScheme!=INTERNET_SCHEME_HTTPS) ||
        components.dwHostNameLength==0||components.dwUserNameLength||components.dwPasswordLength)
        throw Failure("invalid_argument","Only HTTP(S) URLs with a hostname and no credentials are supported");
    const HRESULT initialized=CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED|COINIT_DISABLE_OLE1DDE);
    if (FAILED(initialized)&&initialized!=RPC_E_CHANGED_MODE)
        throw Failure("browser_open_failed","Cannot initialize Windows shell",static_cast<unsigned long>(initialized));
    struct Cleanup { bool initialized; ~Cleanup(){if(initialized) CoUninitialize();} } cleanup{SUCCEEDED(initialized)};
    SHELLEXECUTEINFOW info{}; info.cbSize=sizeof(info);
    info.fMask=SEE_MASK_FLAG_NO_UI|SEE_MASK_NOASYNC;
    info.lpVerb=L"open"; info.lpFile=url.c_str(); info.nShow=SW_SHOWNORMAL;
    if (!ShellExecuteExW(&info)) throw Failure("browser_open_failed","Windows could not open the URL",GetLastError());
    return {{"url",input},{"status","shell_accepted"},{"page_loaded_verified",false}};
}

Json windows_location(const Json& params) {
    keys(params,{"timeout_seconds"});
    const int timeout=integer(params,"timeout_seconds",4,1,10);
    const HRESULT initialized=RoInitialize(RO_INIT_MULTITHREADED);
    if (FAILED(initialized)&&initialized!=RPC_E_CHANGED_MODE)
        throw Failure("location_unavailable","Windows location runtime is unavailable",static_cast<unsigned long>(initialized));
    struct Cleanup { bool initialized; ~Cleanup(){if(initialized) RoUninitialize();} } cleanup{SUCCEEDED(initialized)};
    try {
        using namespace winrt::Windows::Devices::Geolocation;
        Geolocator locator;
        locator.DesiredAccuracy(PositionAccuracy::Default);
        // Respect existing OS consent. The headless kernel never prompts on a UI thread.
        const auto position=locator.GetGeopositionAsync(std::chrono::minutes(5),std::chrono::seconds(timeout)).get();
        const auto coordinate=position.Coordinate();
        const auto point=coordinate.Point().Position();
        return {{"latitude",point.Latitude},{"longitude",point.Longitude},
            {"accuracy_meters",coordinate.Accuracy()},{"source","windows"},
            {"sample_age_seconds",std::chrono::duration<double>(winrt::clock::now()-coordinate.Timestamp()).count()},
            {"approximate",coordinate.Accuracy()>1000.0}};
    } catch (const winrt::hresult_error& e) {
        throw Failure("location_unavailable","Windows location is disabled, not permitted, or unavailable. Check Windows location privacy settings.",static_cast<unsigned long>(e.code().value));
    }
}
}
