#pragma once
#include <windows.h>
#include <jarvis/kernel.hpp>
#include <map>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace jarvis {
struct Failure : std::runtime_error {
    std::string code;
    unsigned long native_code;
    Failure(std::string c, std::string message, unsigned long native = 0)
        : std::runtime_error(std::move(message)), code(std::move(c)), native_code(native) {}
};
std::wstring wide(const std::string& text);
std::string utf8(const std::wstring& text);
std::string utc_now();
void keys(const Json& object, std::initializer_list<const char*> allowed);
int integer(const Json& object, const char* name, int fallback, int low, int high);
std::string string_value(const Json& object, const char* name);
Json open_web_url(const Json& params);
Json windows_location(const Json& params);

class Handle {
    HANDLE value_ = nullptr;
public:
    explicit Handle(HANDLE h = nullptr) : value_(h) {}
    ~Handle() { if (value_ && value_ != INVALID_HANDLE_VALUE) CloseHandle(value_); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    Handle(Handle&& other) noexcept : value_(other.value_) { other.value_ = nullptr; }
    Handle& operator=(Handle&& other) noexcept {
        if (this != &other) { if (value_ && value_ != INVALID_HANDLE_VALUE) CloseHandle(value_); value_ = other.value_; other.value_ = nullptr; }
        return *this;
    }
    HANDLE get() const { return value_; }
    explicit operator bool() const { return value_ && value_ != INVALID_HANDLE_VALUE; }
};
struct Application { std::wstring path; std::vector<std::wstring> args; bool hidden = false; };
class Actions {
public:
    explicit Actions(const Json& config);
    bool enabled() const { return enabled_; }
    Json invoke(const std::string& method, const Json& params);
private:
    bool enabled_ = false;
    std::map<std::string, Application> apps_;
    std::map<DWORD, Handle> children_;
};
}
