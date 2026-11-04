#include "internal.hpp"
#include "probes/process_probe.h"
#include <chrono>
#include <mutex>

namespace jarvis {
struct Kernel::Impl { Actions actions; std::mutex mutex; explicit Impl(const Json& config):actions(config){} };
Kernel::Kernel(const Json& config):impl_(std::make_unique<Impl>(config)){}
Kernel::~Kernel()=default;

Json capabilities(bool enable_actions) {
    const auto object=[](Json properties,Json required=Json::array()) {
        return Json{{"type","object"},{"properties",properties},{"required",required},{"additionalProperties",false}};
    };
    const Json empty=object(Json::object());
    const Json top={{"type","integer"},{"minimum",1},{"maximum",100}};
    Json tools=Json::array();
    const auto add=[&](const char* name,const char* description,bool read_only,Json parameters) {
        tools.push_back({{"name",name},{"description",description},{"read_only",read_only},
            {"enabled",read_only||enable_actions},{"parameters",std::move(parameters)}});
    };
    add("ping","Check the local native kernel",true,empty);
    add("capabilities","List commands and their JSON schemas",true,empty);
    add("system_snapshot","Collect selected Windows metrics in parallel",true,
        object({{"checks",{{"type","array"},{"minItems",1},{"maxItems",8},{"items",{{"type","string"},{"enum",{"cpu","memory","disk","network","processes","battery","startup","system"}}}}}},{"top_processes",top}}));
    add("list_processes","Sample top processes by CPU and working set",true,object({{"top_n",top}}));
    add("list_windows","List visible top-level windows",true,object({{"limit",{{"type","integer"},{"minimum",1},{"maximum",500}}}}));
    add("get_audio","Read the default playback endpoint volume and mute state",true,empty);
    add("list_apps","List registered application IDs and executable availability",true,empty);
    add("get_location","Get Windows location if OS privacy settings allow it",true,
        object({{"timeout_seconds",{{"type","integer"},{"minimum",1},{"maximum",10}}}}));
    add("open_url","Open an HTTP or HTTPS URL in the default browser",false,
        object({{"url",{{"type","string"},{"minLength",1},{"maxLength",4096}}}},Json::array({"url"})));
    add("open_telegram_dialog","Open a Telegram chat by a resolved public username or contact phone",false,
        object({{"username",{{"type","string"},{"maxLength",32}}},{"phone",{{"type","string"},{"maxLength",15}}}}));
    add("launch_app","Launch an application registered by the local configuration",false,
        object({{"app_id",{{"type","string"},{"minLength",1}}}},Json::array({"app_id"})));
    add("stop_app","Terminate only a child launched by this kernel instance",false,
        object({{"pid",{{"type","integer"},{"minimum",1},{"maximum",4294967295ULL}}}},Json::array({"pid"})));
    add("focus_window","Request foreground activation of an enumerated window",false,
        object({{"window_id",{{"type","string"}}},{"pid",{{"type","integer"},{"minimum",1},{"maximum",4294967295ULL}}}},Json::array({"window_id","pid"})));
    add("set_volume","Set the default playback volume, percent 0..100",false,
        object({{"percent",{{"type","number"},{"minimum",0},{"maximum",100}}}},Json::array({"percent"})));
    add("set_mute","Set mute on the default playback endpoint",false,
        object({{"muted",{{"type","boolean"}}}},Json::array({"muted"})));
    return {{"version",kVersion},{"protocol_version",1},{"actions_enabled",enable_actions},{"tools",tools}};
}

Json Kernel::execute(const std::string& input) {
    const auto start=std::chrono::steady_clock::now();
    std::lock_guard<std::mutex> guard(impl_->mutex);
    Json id=nullptr,result=nullptr,error=nullptr;
    try {
        if (input.size()>kMaxRequestBytes) throw Failure("request_too_large","Maximum request size is 1 MiB");
        const auto request=Json::parse(input);
        keys(request,{"id","method","params","protocol_version"});
        if (request.contains("id")) {
            const auto& value=request["id"];
            if (!(value.is_null()||value.is_string()||value.is_number_integer()) || (value.is_string()&&value.get_ref<const std::string&>().size()>512))
                throw Failure("invalid_argument","id must be null, an integer or a string of at most 512 bytes");
            id=value;
        }
        if (integer(request,"protocol_version",1,1,1)!=1) throw Failure("invalid_argument","Unsupported protocol version");
        const auto method=string_value(request,"method");
        const Json params=request.contains("params")?request["params"]:Json::object();
        if (!params.is_object()) throw Failure("invalid_argument","params must be an object");
        if (method=="ping") { keys(params,{}); result={{"version",kVersion},{"status","ready"}}; }
        else if (method=="capabilities") { keys(params,{}); result=capabilities(impl_->actions.enabled()); }
        else if (method=="system_snapshot") result=collect_snapshot(params);
        else if (method=="list_processes") { keys(params,{"top_n"}); result=probes::CollectProcessMetrics(integer(params,"top_n",10,1,100)); }
        else if (method=="get_location") result=windows_location(params);
        else if (method=="list_windows"||method=="get_audio"||method=="list_apps"||method=="open_url"||method=="open_telegram_dialog"||method=="launch_app"||method=="stop_app"||method=="focus_window"||method=="set_volume"||method=="set_mute")
            result=impl_->actions.invoke(method,params);
        else throw Failure("method_not_found","Unknown method: "+method);
    } catch (const Json::parse_error&) { error={{"code","parse_error"},{"message","Request must contain valid UTF-8 JSON"}}; }
      catch (const Failure& e) { error={{"code",e.code},{"message",e.what()}}; if (e.native_code) error["native_code"]=e.native_code; }
      catch (const Json::exception& e) { error={{"code","invalid_argument"},{"message",e.what()}}; }
      catch (const std::exception& e) { error={{"code","internal_error"},{"message",e.what()}}; }
    return {{"protocol_version",1},{"id",id},{"ok",error.is_null()},
        {"timestamp_utc",utc_now()},{"elapsed_ms",std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count()},
        {"result",error.is_null()?result:Json(nullptr)},{"error",error}};
}
}
