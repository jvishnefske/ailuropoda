# cmake/Modules/Finddoctest.cmake
# Find doctest, a header-only test framework.
# This module defines:
#   doctest_FOUND - True if doctest was found
#   doctest_INCLUDE_DIRS - The directory containing doctest.h

find_path(doctest_INCLUDE_DIRS
  NAMES doctest/doctest.h
  PATHS
    ${CMAKE_PREFIX_PATH}/include # Look in CMAKE_PREFIX_PATH first (set by test fixture)
    ${CMAKE_CURRENT_SOURCE_DIR}/build/persistent_deps_install/include # Specific persistent cache
  DOC "Path to doctest.h"
)

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(doctest DEFAULT_MSG doctest_INCLUDE_DIRS)

if(doctest_FOUND)
  set(doctest_INCLUDE_DIRS ${doctest_INCLUDE_DIRS})
  message(STATUS "Found doctest: ${doctest_INCLUDE_DIRS}")
else()
  message(STATUS "doctest not found.")
endif()

mark_as_advanced(doctest_INCLUDE_DIRS)
