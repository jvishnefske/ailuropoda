cmake_minimum_required(VERSION 3.14)
project(cbor_project C CXX) # Add CXX for potential future use, and ensure C is enabled

include(FetchContent)

FetchContent_Declare(
  tinycbor
  URL https://github.com/intel/tinycbor/archive/refs/tags/v0.6.1.tar.gz
)

FetchContent_MakeAvailable(tinycbor)

find_package(Python3 COMPONENTS Interpreter REQUIRED)

# Command to ensure uv is installed for the Python interpreter CMake uses
add_custom_command(
    OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/.uv_installed_marker # A sentinel file
    COMMAND ${Python3_EXECUTABLE} -m pip install uv
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    COMMENT "Ensuring uv is installed for CMake's Python interpreter"
    VERBATIM
)
add_custom_target(ensure_uv_installed ALL DEPENDS ${CMAKE_CURRENT_BINARY_DIR}/.uv_installed_marker)


# Define the virtual environment directory
set(VENV_DIR "${CMAKE_CURRENT_BINARY_DIR}/.venv")

# Command to create and update the uv virtual environment and install pycparser
add_custom_command(
    OUTPUT ${VENV_DIR}/bin/python # A sentinel file for the venv
    COMMAND ${Python3_EXECUTABLE} -m uv venv ${VENV_DIR}
    COMMAND ${VENV_DIR}/bin/uv pip install pycparser
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    COMMENT "Setting up Python virtual environment with uv and installing pycparser"
    DEPENDS cbor_codegen.py my_data.h ensure_uv_installed # Depend on uv being installed
    VERBATIM
)
add_custom_target(uv_venv_setup ALL DEPENDS ${VENV_DIR}/bin/python)

# Custom command to run the CBOR code generator
add_custom_command(
    OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/cbor_generated.h
           ${CMAKE_CURRENT_BINARY_DIR}/cbor_generated.c
    COMMAND ${VENV_DIR}/bin/python ${CMAKE_CURRENT_SOURCE_DIR}/cbor_codegen.py
            ${CMAKE_CURRENT_SOURCE_DIR}/my_data.h
            --output-dir ${CMAKE_CURRENT_BINARY_DIR}
            --cpp-path ${CMAKE_C_COMPILER} # Use the C compiler as preprocessor
            --cpp-args "-I${CMAKE_CURRENT_SOURCE_DIR}" # Include my_data.h's directory
    DEPENDS cbor_codegen.py my_data.h uv_venv_setup # Depend on the venv setup
    COMMENT "Generating CBOR encode/decode code for my_data.h"
    VERBATIM
)
add_custom_target(cbor_codegen_target ALL
    DEPENDS ${CMAKE_CURRENT_BINARY_DIR}/cbor_generated.h
            ${CMAKE_CURRENT_BINARY_DIR}/cbor_generated.c
)

# Add your source files here
add_executable(my_app
    my_data.c
    ${CMAKE_CURRENT_BINARY_DIR}/cbor_generated.c
)

# Link against tinycbor
target_link_libraries(my_app PRIVATE tinycbor)

# Add include directory for generated header
target_include_directories(my_app PRIVATE ${CMAKE_CURRENT_BINARY_DIR})

# Ensure code generation runs before compilation
add_dependencies(my_app cbor_codegen_target)
