#pragma once
#include <nlohmann/json.hpp>
#include <memory>
#include <string>

namespace jarvis {
using Json = nlohmann::json;
constexpr const char* kVersion = "0.7.0";
constexpr std::size_t kMaxRequestBytes = 1024 * 1024;

class Kernel final {
public:
    explicit Kernel(const Json& config = Json::object());
    ~Kernel();
    Kernel(const Kernel&) = delete;
    Kernel& operator=(const Kernel&) = delete;
    Json execute(const std::string& request);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
Json collect_snapshot(const Json& params);
Json capabilities(bool enable_actions);
}
