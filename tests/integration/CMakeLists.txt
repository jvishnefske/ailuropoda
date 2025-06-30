# CMakeLists.txt for Ailuropoda integration tests
cmake_minimum_required(VERSION 3.15)
project(AiluropodaIntegrationTests C CXX)

# Include the dependency management script from the project root.
# This assumes dependency.cmake is in the parent directory or a known path.
# We expect the main project's CMakeLists.txt to handle FetchContent for shared dependencies.
# However, for standalone testing or if this is run as a sub-project without parent setup,
# we can call setup_dependencies directly here.
# For now, let's assume `setup_dependencies` is available, possibly through a parent.
# If running this CMakeLists.txt directly for testing, you'd call setup_dependencies() here.
# If add_subdirectory'd, the parent might already have set them up.

# For integration tests, we need the generated code, our test harness, and tinycbor/doctest.

# The generated code will be located in a path passed by the test script (e.g., GENERATED_CODE_DIR).
# We add it as a subdirectory to get its targets.
if(NOT DEFINED GENERATED_CODE_DIR)
    message(FATAL_ERROR "GENERATED_CODE_DIR must be defined for integration tests.")
endif()

# Add the generated CBOR library as a subdirectory.
# Its CMakeLists.txt handles finding TinyCBOR and generating its library.
add_subdirectory(${GENERATED_CODE_DIR} generated_cbor_build)

# Ensure dependencies are available for the test executable
# Call setup_dependencies here to ensure they are available even if not run from root
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/../../dependency.cmake")
    include("${CMAKE_CURRENT_SOURCE_DIR}/../../dependency.cmake")
    setup_dependencies()
else()
    message(WARNING "dependency.cmake not found. Assuming TinyCBOR and Doctest are provided externally.")
    find_package(TinyCBOR CONFIG REQUIRED)
    find_package(doctest CONFIG REQUIRED) # Doctest often provides a config file as well
endif()

# Add the test executable
add_executable(simple_data_test_harness simple_data_test_harness.cpp)

# Link the test executable against the generated library and other dependencies
target_link_libraries(simple_data_test_harness PRIVATE
    cbor_generated # The library target name defined in generated_cbor_build/CMakeLists.txt
    TinyCBOR::tinycbor # Link against the TinyCBOR target (from FetchContent or find_package)
    doctest::doctest # Link against the doctest target (from FetchContent or find_package)
)

# Add include directories for the test harness
target_include_directories(simple_data_test_harness PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR} # For simple_data_test_harness.cpp itself
    ${GENERATED_CODE_DIR}       # For cbor_generated.h
    ${CMAKE_CURRENT_SOURCE_DIR}/../.. # For simple_data.h (original input header)
)

# Add the test to CTest
add_test(NAME AiluropodaSimpleDataIntegrationTest COMMAND simple_data_test_harness)
message(STATUS "Integration test 'AiluropodaSimpleDataIntegrationTest' configured.")
