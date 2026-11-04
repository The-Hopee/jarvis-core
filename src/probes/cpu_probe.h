// Adapted from evo-wnd system_doctor. See docs/PROVENANCE.md.
#pragma once

#include <nlohmann/json.hpp>

namespace jarvis::probes {

// Blocks for ~kDeltaSampleIntervalMs (two PDH samples are required to compute
// a percentage). Call this from its own thread if it needs to overlap with
// other delta-based probes.
nlohmann::json CollectCpuMetrics();

}  // namespace jarvis::probes
