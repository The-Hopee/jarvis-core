// Adapted from evo-wnd system_doctor. See docs/PROVENANCE.md.
#pragma once

#include <nlohmann/json.hpp>

namespace jarvis::probes {

// Blocks for ~kDeltaSampleIntervalMs to compute per-adapter throughput.
nlohmann::json CollectNetworkMetrics();

}  // namespace jarvis::probes
