set(EXECUTABLE_OUTPUT_PATH ${PROJECT_BINARY_DIR}/test)

include_directories(../src)

# msvc doesn't export all symbols
if(NOT (WIN32 AND BUILD_SHARED_LIBS))
  find_package(Python3 COMPONENTS Interpreter REQUIRED)
  add_executable(llm_rerank_test
    llm_rerank_filter_test.cc
    llm_scorer_protocol_test.cc
    rerank_plan_test.cc
    $<TARGET_OBJECTS:rime-llm-rerank-objs>)
  target_link_libraries(llm_rerank_test
    ${rime_library}
    ${GTEST_LIBRARIES})
  if(BUILD_SHARED_LIBS)
    target_compile_definitions(llm_rerank_test PRIVATE RIME_IMPORTS)
  endif()
  target_compile_definitions(llm_rerank_test PRIVATE
    LLM_RERANK_DAEMON_DIR="${CMAKE_CURRENT_SOURCE_DIR}/../daemon"
    LLM_RERANK_PYTHON="${Python3_EXECUTABLE}")

  add_test(NAME llm_rerank_test
    COMMAND llm_rerank_test
    WORKING_DIRECTORY ${EXECUTABLE_OUTPUT_PATH})
endif()
