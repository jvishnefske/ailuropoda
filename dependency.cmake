# dependency.cmake
# This file defines functions for managing external dependencies using FetchContent.

include(FetchContent)

# Function to set up all dependencies
function(setup_dependencies)
    # Configure TinyCBOR via FetchContent
    FetchContent_Declare(
        tinycbor_proj
        GIT_REPOSITORY https://github.com/intel/tinycbor.git
        GIT_TAG        v0.6.1 # Use a specific tag for stability
        SOURCE_DIR     "${CMAKE_BINARY_DIR}/_deps/tinycbor-src"
        BINARY_DIR     "${CMAKE_BINARY_DIR}/_deps/tinycbor-build"
        CONFIGURE_COMMAND "" # TinyCBOR does not need a special configure command beyond CMake
        BUILD_COMMAND ""     # Build is handled by add_subdirectory
        INSTALL_COMMAND ""   # No install needed; targets are directly available
    )
    FetchContent_MakeAvailable(tinycbor_proj)

    # Alias the target for consistency (tinycbor_proj adds tinycbor directly)
    if(NOT TARGET TinyCBOR::tinycbor)
        add_library(TinyCBOR::tinycbor INTERFACE IMPORTED)
        # Assuming the library itself is tinycbor (check TinyCBOR's CMakeLists.txt)
        set_target_properties(TinyCBOR::tinycbor PROPERTIES
            INTERFACE_LINK_LIBRARIES "tinycbor" # Link to the actual target provided by TinyCBOR
            INTERFACE_INCLUDE_DIRECTORIES "${tinycbor_SOURCE_DIR}" # Expose its include directory
        )
    endif()

    message(STATUS "TinyCBOR setup via FetchContent.")

    # Configure Doctest via FetchContent (single-header)
    FetchContent_Declare(
        doctest_proj
        GIT_REPOSITORY https://github.com/doctest/doctest.git
        GIT_TAG        v2.4.11 # Use a specific tag for stability
        SOURCE_DIR     "${CMAKE_BINARY_DIR}/_deps/doctest-src"
        BINARY_DIR     "${CMAKE_BINARY_DIR}/_deps/doctest-build"
        CONFIGURE_COMMAND ""
        BUILD_COMMAND ""
        INSTALL_COMMAND ""
    )
    FetchContent_MakeAvailable(doctest_proj)

    # Doctest is a header-only library, so we just need its include directory.
    # Its CMakeLists.txt automatically defines a target `doctest`.
    # We can create an alias for consistency if needed, but the original target name is fine.
    # Doctest usually provides a doctest::doctest target if configured correctly.
    if(NOT TARGET doctest::doctest)
         # In some Doctest versions, it might just expose the include dir.
         # For simplicity, we directly add the include directory here if the target isn't found.
         # For more robust integration, one might use find_package(doctest) after FetchContent_MakeAvailable.
         message(STATUS "Doctest target 'doctest::doctest' not found. Assuming header-only and setting include directory directly.")
         include_directories(${doctest_SOURCE_DIR}/doctest) # Assuming the header is in doctest/doctest.h relative to source dir
    endif()
    message(STATUS "Doctest setup via FetchContent.")
endfunction()
