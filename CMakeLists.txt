cmake_minimum_required(VERSION 3.24)
project(jarvis_core VERSION 0.5.0 LANGUAGES CXX)
if(NOT WIN32)
    message(FATAL_ERROR "Jarvis Core requires Windows and the Windows SDK")
endif()
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
include(FetchContent)
FetchContent_Declare(nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG 9cca280a4d0ccf0c08f47a99aa71d1b0e52f8d03)
FetchContent_MakeAvailable(nlohmann_json)

add_library(jarvis_runtime STATIC
    src/kernel.cpp src/actions.cpp src/desktop.cpp src/metrics.cpp src/windows_util.cpp
    src/probes/probe_utils.cpp src/probes/cpu_probe.cpp
    src/probes/memory_probe.cpp src/probes/process_probe.cpp
    src/probes/disk_probe.cpp src/probes/network_probe.cpp
    src/probes/battery_probe.cpp src/probes/startup_probe.cpp
    src/probes/system_probe.cpp src/slowdown_rules.cpp)
target_include_directories(jarvis_runtime PUBLIC include PRIVATE src)
target_link_libraries(jarvis_runtime PUBLIC nlohmann_json::nlohmann_json
    PRIVATE psapi advapi32 iphlpapi ws2_32 user32 ole32 uuid shell32 winhttp windowsapp)
target_compile_definitions(jarvis_runtime PUBLIC UNICODE _UNICODE NOMINMAX _WIN32_WINNT=0x0A00)
if(MSVC)
    target_compile_options(jarvis_runtime PRIVATE /W4 /permissive- /utf-8)
endif()
add_library(jarvis_core SHARED src/c_api.cpp)
target_link_libraries(jarvis_core PRIVATE jarvis_runtime)
target_compile_definitions(jarvis_core PRIVATE JARVIS_CORE_EXPORTS)
set_target_properties(jarvis_core PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
add_executable(jarvis-core src/main.cpp)
target_link_libraries(jarvis-core PRIVATE jarvis_runtime)
set_target_properties(jarvis-core PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
if(MSVC)
    target_compile_options(jarvis_core PRIVATE /W4 /permissive- /utf-8)
    target_compile_options(jarvis-core PRIVATE /W4 /permissive- /utf-8)
endif()
include(CTest)
if(BUILD_TESTING)
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    add_executable(jarvis-test-child tests/child.cpp)
    set_target_properties(jarvis-test-child PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
    add_test(NAME native_contract
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_SOURCE_DIR}/tests/integration.py"
        --exe $<TARGET_FILE:jarvis-core> --dll $<TARGET_FILE:jarvis_core>
        --child $<TARGET_FILE:jarvis-test-child>)
    set_tests_properties(native_contract PROPERTIES TIMEOUT 60)
endif()
install(TARGETS jarvis-core jarvis_core RUNTIME DESTINATION bin LIBRARY DESTINATION lib)
install(FILES include/jarvis/c_api.h DESTINATION include/jarvis)
