// Window/process patterns reviewed in evo-wnd command_center; standalone implementation.
#include "internal.hpp"
#include <audioclient.h>
#include <endpointvolume.h>
#include <mmdeviceapi.h>
#include <wrl/client.h>
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <iomanip>
#include <sstream>

namespace jarvis {
namespace {
DWORD process_id(const Json& p) {
    if (!p.contains("pid")||!p["pid"].is_number_integer()) throw Failure("invalid_argument","pid must be an integer");
    const auto& v=p["pid"];
    if ((v.is_number_unsigned() && v.get<std::uint64_t>()>MAXDWORD)||(!v.is_number_unsigned() && v.get<std::int64_t>()<=0))
        throw Failure("invalid_argument","pid out of range");
    const auto n=v.get<std::uint64_t>();
    if (!n||n>MAXDWORD) throw Failure("invalid_argument","pid out of range");
    return static_cast<DWORD>(n);
}
std::string window_id(HWND hwnd) { std::ostringstream out; out<<"0x"<<std::hex<<reinterpret_cast<std::uintptr_t>(hwnd); return out.str(); }
struct Windows { Json items=Json::array(); std::string error; };
BOOL CALLBACK enumerate(HWND hwnd,LPARAM parameter) {
    auto& context=*reinterpret_cast<Windows*>(parameter);
    try {
        if (!IsWindowVisible(hwnd)) return TRUE;
        const int size=GetWindowTextLengthW(hwnd);
        if (size<=0) return TRUE;
        std::wstring title(static_cast<std::size_t>(size)+1,L'\0');
        const int copied=GetWindowTextW(hwnd,title.data(),static_cast<int>(title.size()));
        if (!copied) return TRUE; title.resize(copied);
        DWORD pid=0; GetWindowThreadProcessId(hwnd,&pid);
        Handle process(OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid));
        std::wstring path(32768,L'\0'); DWORD count=static_cast<DWORD>(path.size()); Json exe=nullptr;
        if (process && QueryFullProcessImageNameW(process.get(),0,path.data(),&count)) { path.resize(count); exe=utf8(path); }
        context.items.push_back({{"window_id",window_id(hwnd)},{"pid",pid},{"title",utf8(title)},
            {"exe_path",exe},{"minimized",IsIconic(hwnd)!=FALSE},{"foreground",GetForegroundWindow()==hwnd}});
        return TRUE;
    } catch (const std::exception& e) { context.error=e.what(); return FALSE; }
}
Json windows() {
    Windows context; SetLastError(ERROR_SUCCESS);
    if (!EnumWindows(enumerate,reinterpret_cast<LPARAM>(&context))) {
        if (!context.error.empty()) throw Failure("window_enumeration_failed",context.error);
        throw Failure("window_enumeration_failed","EnumWindows failed",GetLastError());
    }
    return context.items;
}
// Windows CRT command-line quoting: backslashes before quotes and at the end are doubled.
std::wstring quote(const std::wstring& value) {
    std::wstring out=L"\""; std::size_t slashes=0;
    for (wchar_t c:value) {
        if (c==L'\\') { ++slashes; continue; }
        if (c==L'\"') { out.append(slashes*2+1,L'\\'); out+=c; }
        else { out.append(slashes,L'\\'); out+=c; }
        slashes=0;
    }
    out.append(slashes*2,L'\\'); out+=L'\"'; return out;
}
void hr_check(HRESULT code,const char* operation) {
    if (FAILED(code)) throw Failure("audio_unavailable",operation,static_cast<unsigned long>(code));
}
struct Audio {
    bool initialized=false;
    Microsoft::WRL::ComPtr<IAudioEndpointVolume> volume;
    Audio() {
        const HRESULT hr=CoInitializeEx(nullptr,COINIT_MULTITHREADED);
        initialized=SUCCEEDED(hr);
        if (FAILED(hr)&&hr!=RPC_E_CHANGED_MODE) hr_check(hr,"CoInitializeEx failed");
        try {
            Microsoft::WRL::ComPtr<IMMDeviceEnumerator> enumerator;
            hr_check(CoCreateInstance(__uuidof(MMDeviceEnumerator),nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&enumerator)),"Create audio enumerator failed");
            Microsoft::WRL::ComPtr<IMMDevice> device;
            hr_check(enumerator->GetDefaultAudioEndpoint(eRender,eConsole,&device),"No default playback endpoint");
            hr_check(device->Activate(__uuidof(IAudioEndpointVolume),CLSCTX_INPROC_SERVER,nullptr,reinterpret_cast<void**>(volume.GetAddressOf())),"Audio endpoint activation failed");
        } catch (...) { volume.Reset(); if (initialized) CoUninitialize(); initialized=false; throw; }
    }
    ~Audio() { volume.Reset(); if (initialized) CoUninitialize(); }
    Json state() {
        float level=0; BOOL muted=FALSE;
        hr_check(volume->GetMasterVolumeLevelScalar(&level),"Get volume failed");
        hr_check(volume->GetMute(&muted),"Get mute failed");
        return {{"volume_percent",static_cast<double>(level)*100.0},{"muted",muted!=FALSE}};
    }
};
}

Actions::Actions(const Json& config) {
    keys(config,{"enable_actions","applications"});
    if (config.contains("enable_actions")) {
        if (!config["enable_actions"].is_boolean()) throw Failure("invalid_argument","enable_actions must be boolean");
        enabled_=config["enable_actions"].get<bool>();
    }
    wchar_t system[MAX_PATH]{};
    const UINT n=GetSystemDirectoryW(system,MAX_PATH);
    if (n && n<MAX_PATH) for (const auto* name:{L"notepad",L"calc",L"mspaint"}) {
        const std::wstring exe=std::wstring(system)+L"\\"+name+L".exe";
        apps_.emplace(utf8(name),Application{exe,{},false});
    }
    if (config.contains("applications")) {
        const auto& apps=config["applications"];
        if (!apps.is_object()||apps.size()>50) throw Failure("invalid_argument","applications must be an object of at most 50 entries");
        for (auto it=apps.begin();it!=apps.end();++it) {
            if (it.key().empty()||it.key().size()>64||it.key().find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")!=std::string::npos)
                throw Failure("invalid_argument","Invalid application ID");
            keys(it.value(),{"path","args","hidden"});
            Application app; app.path=wide(string_value(it.value(),"path"));
            if (!std::filesystem::path(app.path).is_absolute()) throw Failure("invalid_argument","Application path must be absolute");
            if (it.value().contains("hidden")) {
                if (!it.value()["hidden"].is_boolean()) throw Failure("invalid_argument","hidden must be boolean");
                app.hidden=it.value()["hidden"].get<bool>();
            }
            if (it.value().contains("args")) {
                const auto& args=it.value()["args"];
                if (!args.is_array()||args.size()>64) throw Failure("invalid_argument","args must be an array of at most 64 strings");
                for (const auto& arg:args) { if (!arg.is_string()) throw Failure("invalid_argument","Arguments must be strings"); app.args.push_back(wide(arg.get<std::string>())); }
            }
            apps_[it.key()]=std::move(app);
        }
    }
}

Json Actions::invoke(const std::string& method,const Json& params) {
    if (method=="list_windows") {
        keys(params,{"limit"}); const int limit=integer(params,"limit",100,1,500);
        auto items=windows(); const auto total=items.size();
        if (items.size()>static_cast<std::size_t>(limit)) items.erase(items.begin()+limit,items.end());
        return {{"windows",items},{"count",items.size()},{"total_visible",total}};
    }
    if (method=="get_audio") { keys(params,{}); return Audio().state(); }
    if (!enabled_) throw Failure("actions_disabled","Start the kernel with enable_actions=true to execute registered actions");
    if (method=="launch_app") {
        keys(params,{"app_id"}); const auto id=string_value(params,"app_id");
        const auto it=apps_.find(id); if (it==apps_.end()) throw Failure("app_not_registered","Unknown application ID: "+id);
        for (auto child=children_.begin();child!=children_.end();) {
            if (WaitForSingleObject(child->second.get(),0)==WAIT_OBJECT_0) child=children_.erase(child); else ++child;
        }
        if (children_.size()>=128) throw Failure("process_limit","Maximum managed child count is 128");
        const auto& app=it->second;
        if (!std::filesystem::is_regular_file(app.path)) throw Failure("app_not_found","Registered application executable is missing");
        auto extension=std::filesystem::path(app.path).extension().wstring();
        std::transform(extension.begin(),extension.end(),extension.begin(),[](wchar_t c){return static_cast<wchar_t>(towlower(c));});
        if (extension!=L".exe") throw Failure("invalid_argument","Only registered .exe applications can be launched");
        std::wstring command=quote(app.path); for (const auto& arg:app.args) command+=L" "+quote(arg);
        if (command.size()>=32767) throw Failure("invalid_argument","Windows command line too long");
        STARTUPINFOW si{}; si.cb=sizeof(si); si.dwFlags=STARTF_USESHOWWINDOW; si.wShowWindow=app.hidden?SW_HIDE:SW_SHOWNORMAL;
        PROCESS_INFORMATION pi{}; const auto cwd=std::filesystem::path(app.path).parent_path().wstring();
        if (!CreateProcessW(app.path.c_str(),command.data(),nullptr,nullptr,FALSE,app.hidden?CREATE_NO_WINDOW:0,nullptr,cwd.c_str(),&si,&pi))
            throw Failure("launch_failed","CreateProcessW failed",GetLastError());
        Handle thread(pi.hThread); Handle process(pi.hProcess);
        children_.insert_or_assign(pi.dwProcessId,std::move(process));
        return {{"app_id",id},{"pid",pi.dwProcessId},{"status","process_created"},{"application_ready_verified",false}};
    }
    if (method=="stop_app") {
        keys(params,{"pid"}); const DWORD pid=process_id(params); const auto it=children_.find(pid);
        if (it==children_.end()) throw Failure("process_not_owned","Only processes launched by this kernel instance can be stopped");
        const DWORD state=WaitForSingleObject(it->second.get(),0);
        if (state==WAIT_OBJECT_0) { children_.erase(it); return {{"pid",pid},{"status","already_exited"}}; }
        if (state!=WAIT_TIMEOUT) throw Failure("process_state_failed","Cannot inspect child process",GetLastError());
        if (!TerminateProcess(it->second.get(),1)) throw Failure("stop_failed","TerminateProcess failed",GetLastError());
        if (WaitForSingleObject(it->second.get(),3000)!=WAIT_OBJECT_0) throw Failure("stop_timeout","Child termination was requested but not verified");
        children_.erase(it); return {{"pid",pid},{"status","terminated"},{"verified",true}};
    }
    if (method=="focus_window") {
        keys(params,{"window_id","pid"}); const auto id=string_value(params,"window_id"); const DWORD pid=process_id(params);
        for (const auto& window:windows()) if (window["window_id"]==id&&window["pid"]==pid) {
            const auto value=std::stoull(id,nullptr,16); const auto hwnd=reinterpret_cast<HWND>(static_cast<std::uintptr_t>(value));
            DWORD actual_pid=0; GetWindowThreadProcessId(hwnd,&actual_pid);
            if (!IsWindow(hwnd)||actual_pid!=pid) throw Failure("stale_window","Window identity changed");
            if (IsIconic(hwnd)) ShowWindowAsync(hwnd,SW_RESTORE);
            SetForegroundWindow(hwnd);
            if (GetForegroundWindow()!=hwnd) throw Failure("foreground_denied","Windows did not grant foreground activation");
            return {{"window_id",id},{"pid",pid},{"foreground",true}};
        }
        throw Failure("window_not_found","Window ID and PID do not identify a current visible window");
    }
    if (method=="set_volume") {
        keys(params,{"percent"});
        if (!params.contains("percent")||!params["percent"].is_number()) throw Failure("invalid_argument","percent must be a number from 0 to 100");
        const auto percent=params["percent"].get<double>();
        if (!std::isfinite(percent)||percent<0||percent>100) throw Failure("invalid_argument","percent out of range");
        Audio endpoint; hr_check(endpoint.volume->SetMasterVolumeLevelScalar(static_cast<float>(percent/100.0),nullptr),"Set volume failed"); return endpoint.state();
    }
    if (method=="set_mute") {
        keys(params,{"muted"}); if (!params.contains("muted")||!params["muted"].is_boolean()) throw Failure("invalid_argument","muted must be boolean");
        Audio endpoint; hr_check(endpoint.volume->SetMute(params["muted"].get<bool>()?TRUE:FALSE,nullptr),"Set mute failed"); return endpoint.state();
    }
    throw Failure("method_not_found","Unknown action");
}
}
