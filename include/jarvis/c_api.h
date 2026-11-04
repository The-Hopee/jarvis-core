#pragma once
#ifdef _WIN32
#ifdef JARVIS_CORE_EXPORTS
#define JARVIS_API __declspec(dllexport)
#else
#define JARVIS_API __declspec(dllimport)
#endif
#else
#define JARVIS_API
#endif
#ifdef __cplusplus
extern "C" {
#endif
/* Returns NULL on invalid configuration. UTF-8 JSON; NULL config means {}. */
JARVIS_API void* jarvis_create(const char* config_json);
/* Owned UTF-8 result: release exclusively with jarvis_free_string. */
JARVIS_API char* jarvis_execute(void* kernel, const char* request_json);
JARVIS_API void jarvis_free_string(char* result);
JARVIS_API void jarvis_destroy(void* kernel);
JARVIS_API const char* jarvis_version(void);
#ifdef __cplusplus
}
#endif
