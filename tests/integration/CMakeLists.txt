# CMakeLists.txt for Ailuropoda integration tests
cmake_minimum_required(VERSION 3.15)
project(AiluropodaIntegrationTests C CXX)

# Define paths relative to the current test directory
set(INTEGRATION_TEST_DIR ${CMAKE_CURRENT_SOURCE_DIR})
set(PROJECT_ROOT ${INTEGRATION_TEST_DIR}/../..)
set(SRC_DIR ${PROJECT_ROOT}/src)
set(TEMPLATES_DIR ${PROJECT_ROOT}/templates)
set(HEADER_FILE ${INTEGRATION_TEST_DIR}/simple_data.h)

# Define output directory for generated code within the current build tree
set(GENERATED_OUTPUT_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated_code")

# Ensure the output directory exists for the Python script
file(MAKE_DIRECTORY ${GENERATED_OUTPUT_DIR})

# Define the paths for the generated files
set(GENERATED_C_FILE "${GENERATED_OUTPUT_DIR}/cbor_generated.c")
set(GENERATED_H_FILE "${GENERATED_OUTPUT_DIR}/cbor_generated.h")

# Find Python interpreter (from main CMakeLists.txt or system PATH)
find_package(Python3 COMPONENTS Interpreter REQUIRED)

# Find C preprocessor (cpp) executable
find_program(CPP_EXECUTABLE NAMES cpp PATHS /usr/bin /bin /opt/local/bin NO_DEFAULT_PATH)
if(NOT CPP_EXECUTABLE)
    message(WARNING "Could not find 'cpp' preprocessor. Using fallback 'cpp'.")
    set(CPP_EXECUTABLE "cpp")
endif()

# Define common cpp_args. In a real project, these might come from user/env.
# Add -D__STDC_WANT_LIB_EXT1__ which is needed by pycparser for some system headers.
set(CPP_ARGS -E -D__STDC_WANT_LIB_EXT1__)

# Construct the Python command and environment to run the code generator as a module
# Set PYTHONPATH to include the 'src' directory so 'ailuropoda' can be found.
set(PYTHON_ENV_ARGS "PYTHONPATH=${SRC_DIR}")

# Add custom command to run the code generator
add_custom_command(
    OUTPUT
        ${GENERATED_C_FILE}
        ${GENERATED_H_FILE}
    COMMAND
        ${CMAKE_COMMAND} -E env ${PYTHON_ENV_ARGS}
        ${Python3_EXECUTABLE} -m ailuropoda # Correctly invoke python -m module as separate args
        ${HEADER_FILE}
        --output-dir ${GENERATED_OUTPUT_DIR}
        --cpp-path ${CPP_EXECUTABLE}
        --templates-dir ${TEMPLATES_DIR}
        --cpp-args ${CPP_ARGS}
    DEPENDS
        ${HEADER_FILE}
        ${SRC_DIR}/ailuropoda/cbor_codegen.py # Dependency on the generator script
        ${TEMPLATES_DIR}/cbor_generated.c.jinja # Dependency on templates used by generator
        ${TEMPLATES_DIR}/cbor_generated.h.jinja
        ${TEMPLATES_DIR}/CMakeLists.txt.jinja # Dependency on CMakeLists template
        ${PROJECT_ROOT}/dependency.cmake # Dependency on the dependency setup script
    COMMENT "Generating CBOR code for ${HEADER_FILE} in integration test"
    VERBATIM
)

# Define the integration test executable
set(TEST_HARNESS_SRC ${INTEGRATION_TEST_DIR}/simple_data_test_harness.cpp)
set(TEST_EXECUTABLE_NAME "ailuropoda_simple_data_integration_test")

add_executable(${TEST_EXECUTABLE_NAME}
    ${TEST_HARNESS_SRC}
    ${GENERATED_C_FILE} # Include the generated C file as a source for this executable
)

# Set include directories for the test executable
target_include_directories(${TEST_EXECUTABLE_NAME} PRIVATE
    $<BUILD_INTERFACE:${GENERATED_OUTPUT_DIR}> # For cbor_generated.h
    $<BUILD_INTERFACE:${INTEGRATION_TEST_DIR}> # For simple_data.h
    $<BUILD_INTERFACE:${tinycbor_SOURCE_DIR}>  # For tinycbor headers (provided by root setup_dependencies)
    $<BUILD_INTERFACE:${doctest_proj_SOURCE_DIR}> # For doctest headers (provided by root setup_dependencies)
)

# Link the test executable against TinyCBOR and Doctest
target_link_libraries(${TEST_EXECUTABLE_NAME} PRIVATE
    TinyCBOR::tinycbor # Provided by FetchContent in root dependency.cmake
    doctest::doctest   # Provided by FetchContent in root dependency.cmake
)


include(${PROJECT_ROOT}/dependency.cmake REQUIRED)
setup_dependencies()
# Add the test to CTest
add_test(NAME ${TEST_EXECUTABLE_NAME} COMMAND ${TEST_EXECUTABLE_NAME})
MESSAGE(STATUS "Added CTest test: ${TEST_EXECUTABLE_NAME}")
