cmake_minimum_required(VERSION 3.14)
project(cbor_project)

include(FetchContent)

FetchContent_Declare(
  tinycbor
  URL https://github.com/intel/tinycbor/archive/refs/tags/v0.6.1.tar.gz
)

FetchContent_MakeAvailable(tinycbor)

# Add your source files here
# add_executable(your_target_name main.c)

# Link against tinycbor
# target_link_libraries(your_target_name PRIVATE tinycbor)
