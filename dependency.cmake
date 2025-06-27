# dependency.cmake
# This file defines functions for managing external dependencies.

function(setup_doctest_single_header)
    # Define the download destination relative to the current binary directory
    set(DOCTEST_HEADER_DEST_DIR ${CMAKE_CURRENT_BINARY_DIR}/thirdparty/doctest)
    set(DOCTEST_HEADER_FILE     ${DOCTEST_HEADER_DEST_DIR}/doctest.h)

    # Create the directory where the header will be stored
    file(MAKE_DIRECTORY ${DOCTEST_HEADER_DEST_DIR})

    # Use CMake's file(DOWNLOAD ...) command to fetch the header.
    # We use a POST_DOWNLOAD step to ensure the directory exists before attempting
    # the download. CMAKE_CURRENT_SOURCE_DIR is a safe place for temp downloads.
    message(STATUS "Downloading doctest.h to ${DOCTEST_HEADER_FILE}...")
    file(DOWNLOAD
        https://raw.githubusercontent.com/doctest/doctest/refs/heads/master/doctest/doctest.h
        ${DOCTEST_HEADER_FILE}
        STATUS download_status
        LOG download_log
        # Other options:
        # TLS_VERIFY OFF # Only use this if you encounter SSL errors and know the risk
    )

    # Check download status
    if(NOT download_status EQUAL 0)
        message(FATAL_ERROR "Failed to download doctest.h: ${download_log}")
    endif()
    message(STATUS "doctest.h downloaded successfully.")

    # Create an INTERFACE library for doctest
    # An INTERFACE library doesn't compile any sources itself. It's used to
    # propagate properties (like include directories, compile definitions)
    # to targets that link against it.
    add_library(doctest_single_header INTERFACE)

    # Add the downloaded header's directory to the interface include directories.
    # This means any target linking to 'doctest_single_header' will get this
    # directory added to its include paths.
    target_include_directories(doctest_single_header INTERFACE
        $<BUILD_INTERFACE:${DOCTEST_HEADER_DEST_DIR}> # For build tree
        $<INSTALL_INTERFACE:include>                   # For install tree (if you were installing it)
    )
    message(STATUS "doctest_single_header INTERFACE library configured.")
endfunction()
