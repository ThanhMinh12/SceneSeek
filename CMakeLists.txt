cmake_minimum_required(VERSION 3.20)
project(SceneSeekCore VERSION 0.2.0 LANGUAGES CXX)

option(SCENESEEK_BUILD_TESTS "Build native unit tests" ON)
option(SCENESEEK_SANITIZERS "Enable address/undefined-behavior checks" OFF)
find_package(Threads REQUIRED)

if(SCENESEEK_SANITIZERS AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
  add_link_options(-fsanitize=address,undefined)
endif()

add_library(sceneseek_core SHARED cpp/src/index.cpp cpp/src/engine.cpp cpp/src/engine_c.cpp)
target_link_libraries(sceneseek_core PUBLIC Threads::Threads)
target_include_directories(sceneseek_core PUBLIC cpp/include)
target_compile_features(sceneseek_core PUBLIC cxx_std_20)
target_compile_options(sceneseek_core PRIVATE
  $<$<CXX_COMPILER_ID:GNU,Clang>:-Wall;-Wextra;-Wpedantic;-Wconversion>
)
set_target_properties(sceneseek_core PROPERTIES
  OUTPUT_NAME sceneseek_core
  POSITION_INDEPENDENT_CODE ON
  WINDOWS_EXPORT_ALL_SYMBOLS ON
)

install(TARGETS sceneseek_core LIBRARY DESTINATION lib RUNTIME DESTINATION bin)
install(DIRECTORY cpp/include/ DESTINATION include)

add_executable(sceneseek_cli cpp/src/cli.cpp)
target_link_libraries(sceneseek_cli PRIVATE sceneseek_core)
target_compile_features(sceneseek_cli PRIVATE cxx_std_20)
set_target_properties(sceneseek_cli PROPERTIES OUTPUT_NAME sceneseek INSTALL_RPATH "$ORIGIN/../lib")
install(TARGETS sceneseek_cli RUNTIME DESTINATION bin)

if(SCENESEEK_BUILD_TESTS)
  enable_testing()
  add_executable(sceneseek_core_tests cpp/src/index_test.cpp)
  target_link_libraries(sceneseek_core_tests PRIVATE sceneseek_core)
  target_compile_features(sceneseek_core_tests PRIVATE cxx_std_20)
  add_test(NAME sceneseek_core_tests COMMAND sceneseek_core_tests)
  add_executable(sceneseek_engine_tests cpp/src/engine_test.cpp)
  target_link_libraries(sceneseek_engine_tests PRIVATE sceneseek_core)
  target_compile_features(sceneseek_engine_tests PRIVATE cxx_std_20)
  add_test(NAME sceneseek_engine_tests COMMAND sceneseek_engine_tests)
  add_test(NAME sceneseek_cli_help COMMAND sceneseek_cli --help)
  add_test(NAME sceneseek_cli_benchmark COMMAND sceneseek_cli benchmark 100 8 3 2)
endif()

