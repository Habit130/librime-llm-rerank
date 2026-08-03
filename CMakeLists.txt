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
set(plugin_deps ${rime_library} PARENT_SCOPE)
set(plugin_modules "llm_rerank" PARENT_SCOPE)

if(BUILD_TEST)
  add_subdirectory(test)
endif()
