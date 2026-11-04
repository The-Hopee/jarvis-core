#include "internal.hpp"
#include <chrono>
#include <ctime>
#include <limits>

namespace jarvis {
std::wstring wide(const std::string& text) {
    if (text.empty()) return {};
    if (text.size() > static_cast<std::size_t>((std::numeric_limits<int>::max)()) || text.find('\0') != std::string::npos)
        throw Failure("invalid_argument", "Invalid UTF-8 string length or embedded NUL");
    const int n = static_cast<int>(text.size());
    const int size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), n, nullptr, 0);
    if (!size) throw Failure("invalid_argument", "Invalid UTF-8", GetLastError());
    std::wstring result(size, L'\0');
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), n, result.data(), size) != size)
        throw Failure("conversion_failed", "UTF-8 conversion failed", GetLastError());
    return result;
}
std::string utf8(const std::wstring& text) {
    if (text.empty()) return {};
    const int n = static_cast<int>(text.size());
    const int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text.data(), n, nullptr, 0, nullptr, nullptr);
    if (!size) throw Failure("conversion_failed", "UTF-16 conversion failed", GetLastError());
    std::string result(size, '\0');
    if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, text.data(), n, result.data(), size, nullptr, nullptr) != size)
        throw Failure("conversion_failed", "UTF-16 conversion failed", GetLastError());
    return result;
}
std::string utc_now() {
    const auto now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
    std::tm t{}; gmtime_s(&t, &now); char buffer[32]{};
    std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &t); return buffer;
}
void keys(const Json& object, std::initializer_list<const char*> allowed) {
    if (!object.is_object()) throw Failure("invalid_argument", "Expected a JSON object");
    for (auto it = object.begin(); it != object.end(); ++it) {
        bool found = false; for (const auto* name : allowed) if (it.key() == name) found = true;
        if (!found) throw Failure("invalid_argument", "Unknown field: " + it.key());
    }
}
int integer(const Json& object, const char* name, int fallback, int low, int high) {
    if (!object.contains(name)) return fallback;
    const auto& v = object.at(name);
    if (!v.is_number_integer() || v.is_boolean()) throw Failure("invalid_argument", std::string(name) + " must be integer");
    if (v.is_number_unsigned() && v.get<std::uint64_t>() > static_cast<std::uint64_t>(high))
        throw Failure("invalid_argument", std::string(name) + " out of range");
    const auto n = v.get<std::int64_t>();
    if (n < low || n > high) throw Failure("invalid_argument", std::string(name) + " out of range");
    return static_cast<int>(n);
}
std::string string_value(const Json& object, const char* name) {
    if (!object.contains(name) || !object.at(name).is_string()) throw Failure("invalid_argument", std::string(name) + " must be string");
    const auto value = object.at(name).get<std::string>();
    if (value.empty() || value.size() > 32768 || value.find('\0') != std::string::npos)
        throw Failure("invalid_argument", std::string(name) + " has invalid length or NUL");
    return value;
}
}
