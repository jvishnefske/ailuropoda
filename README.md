# CBOR Code Generator for C Structs

This repository contains `cbor_codegen.py`, a Python script designed to automate the generation of C code for encoding and decoding C structs into Concise Binary Object Representation (CBOR) format, leveraging the [TinyCBOR](https://github.com/intel/tinycbor) library.

## Intention

Manually writing CBOR serialization and deserialization code for complex C data structures can be tedious, error-prone, and time-consuming. This script aims to eliminate this boilerplate by automatically generating the necessary C functions based on your existing C header file definitions.

## Goals

The primary goals of `cbor_codegen.py` are:

*   **Automate Boilerplate**: Generate `encode_MyStruct()` and `decode_MyStruct()` functions for each `struct` defined in a given C header file.
*   **Integrate with TinyCBOR**: Produce C code that seamlessly uses the `CborEncoder` and `CborValue` APIs from the TinyCBOR library.
*   **Support Common C Types**: Handle a variety of C data types, including:
    *   Basic integers (`int`, `uint64_t`, `char`, etc.)
    *   Floating-point numbers (`float`, `double`)
    *   Booleans (`bool`)
    *   Fixed-size character arrays (e.g., `char name[64]`) as CBOR text strings.
    *   Character pointers (e.g., `char* email`, `const char* notes`) as CBOR text strings.
    *   Nested structs.
    *   Fixed-size arrays of basic types or nested structs.
*   **Simplify Development**: Allow developers to focus on defining their data structures in C headers, and let the script handle the CBOR serialization logic.

## How It Works

The `cbor_codegen.py` script uses `pycparser` to parse a C header file. It then traverses the Abstract Syntax Tree (AST) to identify `struct` definitions and their members. For each `struct`, it generates corresponding C functions:

*   `bool encode_StructName(const struct StructName* data, CborEncoder* encoder);`
*   `bool decode_StructName(struct StructName* data, CborValue* it);`

These generated functions are written to `cbor_generated.h` and `cbor_generated.c` files, which can then be compiled and linked with your application and the TinyCBOR library.

## Usage

1.  **Install `pycparser`**:
    ```bash
    pip install pycparser
    ```
2.  **Run the script**:
    ```bash
    python cbor_codegen.py <your_header_file.h> [--output-dir <output_directory>]
    ```
    Example:
    ```bash
    python cbor_codegen.py my_data.h --output-dir ./generated_code
    ```

This will create `cbor_generated.h` and `cbor_generated.c` in the specified output directory (or the current directory by default).

## Assumptions and Limitations

*   **C Preprocessing**: For complex header files with many `#include` directives or macros, it's recommended to preprocess the header first (e.g., using `gcc -E your_header.h`) and then pass the preprocessed output to `cbor_codegen.py`.
*   **Memory Management for Pointers**: For `char*` and other pointer types during decoding, the generated C code **does not** perform dynamic memory allocation (`malloc`). It assumes that the pointer members in your struct are already pointing to sufficiently large, allocated buffers. You are responsible for managing this memory.
*   **Unsupported C Constructs**:
    *   `union` types are not supported.
    *   Function pointers are detected but skipped.
    *   Multi-dimensional arrays beyond the first dimension are not fully supported for complex types.
    *   Flexible array members are not supported.
*   **Error Handling**: The generated C functions return `false` on any CBOR encoding/decoding error.
*   **CBOR Map Keys**: Struct member names are used directly as CBOR map keys (text strings).
*   **Anonymous Structs**: Anonymous struct definitions that are not part of a `typedef` or a named member are skipped.
