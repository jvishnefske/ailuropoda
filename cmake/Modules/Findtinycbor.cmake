# cmake/Modules/Findtinycbor.cmake
# Find TinyCBOR library and headers.
# This module defines:
#   tinycbor_FOUND - True if TinyCBOR was found
#   tinycbor_INCLUDE_DIRS - The directory containing tinycbor/cbor.h
#   tinycbor_LIBRARIES - The TinyCBOR library

find_path(tinycbor_INCLUDE_DIRS
  NAMES tinycbor/cbor.h
  PATHS
    ${CMAKE_PREFIX_PATH}/include # Look in CMAKE_PREFIX_PATH first (set by test fixture)
    ${CMAKE_CURRENT_SOURCE_DIR}/build/persistent_deps_install/include # Specific persistent cache
  DOC "Path to tinycbor/cbor.h"
)

find_library(tinycbor_LIBRARIES
  NAMES tinycbor
  PATHS
    ${CMAKE_PREFIX_PATH}/lib # Look in CMAKE_PREFIX_PATH first (set by test fixture)
    ${CMAKE_CURRENT_SOURCE_DIR}/build/persistent_deps_install/lib # Specific persistent cache
  DOC "Path to TinyCBOR library"
)

include(FindPackageHandleStandardArgs)
find_package_handle_standard_args(tinycbor DEFAULT_MSG tinycbor_INCLUDE_DIRS tinycbor_LIBRARIES)

if(tinycbor_FOUND)
  set(tinycbor_INCLUDE_DIRS ${tinycbor_INCLUDE_DIRS})
  set(tinycbor_LIBRARIES ${tinycbor_LIBRARIES})
  message(STATUS "Found TinyCBOR: ${tinycbor_INCLUDE_DIRS}, ${tinycbor_LIBRARIES}")
else()
  message(STATUS "TinyCBOR not found.")
endif()

mark_as_advanced(tinycbor_INCLUDE_DIRS tinycbor_LIBRARIES)
