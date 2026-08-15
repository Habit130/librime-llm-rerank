project(rime-llm-rerank)
cmake_minimum_required(VERSION 3.10)

aux_source_directory(src llm_rerank_src)

add_library(rime-llm-rerank-objs OBJECT ${llm_rerank_src})
target_include_directories(rime-llm-rerank-objs SYSTEM PRIVATE
  ${CMAKE_SOURCE_DIR}/deps/opencc/deps/rapidjson-1.1.0)
if(BUILD_SHARED_LIBS)
  set_target_properties(rime-llm-rerank-objs
    PROPERTIES
    POSITION_INDEPENDENT_CODE ON)
endif()

set(plugin_name rime-llm-rerank PARENT_SCOPE)
set(plugin_objs $<TARGET_OBJECTS:rime-llm-rerank-objs> PARENT_SCOPE)
set(plugin_deps ${rime_library} ${LevelDb_LIBRARY} sqlite3 PARENT_SCOPE)
set(plugin_modules "llm_rerank" PARENT_SCOPE)

# Stable C++ seam for the maintenance CLI: creates and verifies empty fact
# stores with the plugin's own fact semantics (Habit130/squirrel#54).
if(NOT (WIN32 AND BUILD_SHARED_LIBS))
  add_executable(rime-llm-rerank-fact-store-tool
    tools/fact_store_tool.cc
    $<TARGET_OBJECTS:rime-llm-rerank-objs>)
  target_include_directories(rime-llm-rerank-fact-store-tool PRIVATE src)
  target_link_libraries(rime-llm-rerank-fact-store-tool
    ${rime_library}
    sqlite3)
  set_target_properties(rime-llm-rerank-fact-store-tool PROPERTIES
    OUTPUT_NAME fact_store_tool
    RUNTIME_OUTPUT_DIRECTORY ${PROJECT_BINARY_DIR}/bin)
  if(BUILD_SHARED_LIBS)
    target_compile_definitions(rime-llm-rerank-fact-store-tool PRIVATE
      RIME_IMPORTS)
  endif()
endif()

if(BUILD_TEST)
  add_subdirectory(test)
endif()
