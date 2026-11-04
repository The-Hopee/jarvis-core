// Adapted from evo-wnd system_doctor. See docs/PROVENANCE.md.
#pragma once

#include <nlohmann/json.hpp>

namespace jarvis::probes {

// top_n <= 0 is treated as "use default" by the caller before this is invoked.
nlohmann::json CollectProcessMetrics(int top_n);

}  // namespace jarvis::probes
