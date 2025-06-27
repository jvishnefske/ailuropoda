# CMakeLists.txt (at project root)
cmake_minimum_required(VERSION 3.15)
project(AiluropodaProject C CXX)

# Add our custom CMake modules path
set(CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake/Modules" ${CMAKE_MODULE_PATH})

# Find TinyCBOR
find_package(tinycbor REQUIRED)

# Find doctest
find_package(doctest REQUIRED)

# Add the generated code as a subdirectory
# The path to the generated code will be passed by the test or user
# via the GENERATED_CODE_DIR variable.
if(NOT DEFINED GENERATED_CODE_DIR)
    message(FATAL_ERROR "GENERATED_CODE_DIR is not set. This CMakeLists.txt expects it to be defined.")
endif()

# Add the generated code as a subdirectory.
# The second argument 'generated_cbor_build' creates a separate binary directory
# for the generated code's build artifacts within the main project's build directory.
add_subdirectory(${GENERATED_CODE_DIR} generated_cbor_build)

# Include directories for the main project (and its subdirectories)
include_directories(
    ${tinycbor_INCLUDE_DIRS}
    ${doctest_INCLUDE_DIRS}
    ${GENERATED_CODE_DIR} # For cbor_generated.h
)

# Link the generated library and test executable to the found dependencies.
# This assumes the generated CMakeLists.txt creates targets named 'cbor_generated'
# and 'cbor_test_simple_data'.
# We need to ensure these targets are linked against the found libraries.
# This is typically done by setting CMAKE_PREFIX_PATH and including the sub-project.
# The sub-project's CMakeLists.txt should then use find_package or target_link_libraries.
# For this setup, the generated CMakeLists.txt already uses find_package(TinyCBOR)
# and links to it. Doctest is header-only, so just include_directories is enough.
