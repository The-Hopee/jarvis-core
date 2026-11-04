// Adapted from evo-wnd system_doctor. See docs/PROVENANCE.md.
#pragma once

#include <nlohmann/json.hpp>

namespace jarvis {

// Evaluates the fixed threshold rules over the collected metrics and returns
// {"issues": [...], "insights": [...], "recommendations": [...]}. Sections
// missing from `metrics` (not requested via checks[]) or carrying an
// "error"/"available":false marker are simply skipped by the relevant rule.
nlohmann::json EvaluateRules(const nlohmann::json& metrics);

}  // namespace jarvis
