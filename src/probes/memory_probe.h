// Adapted from evo-wnd system_doctor. See docs/PROVENANCE.md.
#pragma once

#include <nlohmann/json.hpp>

namespace jarvis::probes {

nlohmann::json CollectMemoryMetrics();

}  // namespace jarvis::probes
