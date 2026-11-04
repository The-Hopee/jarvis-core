#include <jarvis/c_api.h>
#include <jarvis/kernel.hpp>
#include <cstring>
#include <new>

extern "C" {
void* jarvis_create(const char* config_json) {
    try {
        if (config_json && strnlen_s(config_json,jarvis::kMaxRequestBytes+1)>jarvis::kMaxRequestBytes) return nullptr;
        return new jarvis::Kernel(config_json?jarvis::Json::parse(config_json):jarvis::Json::object());
    } catch (...) { return nullptr; }
}
char* jarvis_execute(void* handle,const char* request_json) {
    try {
        jarvis::Json response;
        if (!handle||!request_json) response={{"protocol_version",1},{"id",nullptr},{"ok",false},{"result",nullptr},{"error",{{"code","invalid_argument"},{"message","Null kernel or request"}}}};
        else if (strnlen_s(request_json,jarvis::kMaxRequestBytes+1)>jarvis::kMaxRequestBytes)
            response=static_cast<jarvis::Kernel*>(handle)->execute(std::string(jarvis::kMaxRequestBytes+1,' '));
        else response=static_cast<jarvis::Kernel*>(handle)->execute(request_json);
        const auto text=response.dump(-1,' ',true);
        auto* result=new char[text.size()+1]; std::memcpy(result,text.c_str(),text.size()+1); return result;
    } catch (...) { return nullptr; }
}
void jarvis_free_string(char* text) { delete[] text; }
void jarvis_destroy(void* handle) { try { delete static_cast<jarvis::Kernel*>(handle); } catch (...) {} }
const char* jarvis_version(void) { return jarvis::kVersion; }
}
