# CMakeLists.txt (at project root)
cmake_minimum_required(VERSION 3.15)
project(AiluropodaProject C CXX)

# Include the dependency management script.
# This file is expected to be in the project root.
include(dependency.cmake)

# Call the function to set up common dependencies like TinyCBOR and Doctest.
setup_dependencies()

# Option to build integration tests.
# This can be enabled/disabled via -DBUILD_INTEGRATION_TESTS=ON/OFF
option(BUILD_INTEGRATION_TESTS "Build Ailuropoda integration tests" ON)

if(BUILD_INTEGRATION_TESTS)
    # Add the integration tests subdirectory.
    # The GENERATED_CODE_DIR variable will be passed to this subdirectory's CMakeLists.txt.
    add_subdirectory(tests/integration)
endif()
