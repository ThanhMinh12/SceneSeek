cmake_minimum_required(VERSION 3.20)
project(SceneSeekCore VERSION 0.1.0 LANGUAGES CXX)

option(SCENESEEK_BUILD_TESTS "Build native unit tests" ON)

add_library(sceneseek_core SHARED cpp/src/index.cpp)
target_include_directories(sceneseek_core PUBLIC cpp/include)
target_compile_features(sceneseek_core PUBLIC cxx_std_20)
target_compile_options(sceneseek_core PRIVATE
  $<$<CXX_COMPILER_ID:GNU,Clang>:-Wall;-Wextra;-Wpedantic;-Wconversion>
)
set_target_properties(sceneseek_core PROPERTIES
  OUTPUT_NAME sceneseek_core
  POSITION_INDEPENDENT_CODE ON
)

install(TARGETS sceneseek_core LIBRARY DESTINATION lib RUNTIME DESTINATION bin)
install(DIRECTORY cpp/include/ DESTINATION include)

if(SCENESEEK_BUILD_TESTS)
  enable_testing()
  add_executable(sceneseek_core_tests cpp/src/index_test.cpp)
  target_link_libraries(sceneseek_core_tests PRIVATE sceneseek_core)
  target_compile_features(sceneseek_core_tests PRIVATE cxx_std_20)
  add_test(NAME sceneseek_core_tests COMMAND sceneseek_core_tests)
endif()

