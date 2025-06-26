# 📦 cbor-from-c: Automate CBOR for C Structs

## ✨ Tired of writing tedious, error-prone boilerplate C code for CBOR serialization and deserialization?

**`cbor-from-c`** is your solution! This powerful Python tool automatically generates robust C functions to encode and decode your C structs into Concise Binary Object Representation (CBOR), seamlessly integrating with the TinyCBOR library.

---

## 🚀 Why `cbor-from-c`?

Manually handling CBOR for complex C data structures is a time sink. `cbor-from-c` eliminates this pain, letting you focus on your core logic while it handles the serialization boilerplate.

### Key Features:

*   **Automated Boilerplate**: Generates `encode_MyStruct()` and `decode_MyStruct()` functions for each `struct` in your C header files.
*   **TinyCBOR Integration**: Produces C code fully compatible with the `CborEncoder` and `CborValue` APIs from the [TinyCBOR](https://github.com/intel/tinycbor) library.
*   **Comprehensive Type Support**: Handles a wide range of C types:
    *   Basic integers (`int`, `uint64_t`, `char`, etc.)
    *   Floating-point numbers (`float`, `double`)
    *   Booleans (`bool`)
    *   Fixed-size character arrays (`char name[64]`) as CBOR text strings.
    *   Character pointers (`char* email`, `const char* notes`) as CBOR text strings.
    *   Nested structs.
    *   Fixed-size arrays of basic types or nested structs.
*   **Ready-to-Use Output**: Generates a dedicated output directory containing:
    *   `cbor_generated.h` and `cbor_generated.c` with your encode/decode functions.
    *   A `CMakeLists.txt` file to easily compile the generated code and link against TinyCBOR.
    *   *(Future/Optional)* Helper functions for `cbor2json` and `json2cbor` conversion, simplifying data inspection and interoperability.
*   **Simplified Development**: Define your data structures in C headers, and let `cbor-from-c` handle the rest!

---

## 🛠️ How It Works

`cbor-from-c` leverages `pycparser` to parse your C header file's Abstract Syntax Tree (AST). It identifies `struct` definitions and their members, then intelligently generates the corresponding C encoding and decoding functions.

---

## 📦 Installation

```bash
pip install pycparser
# Or, if you prefer uvx for isolated environments:
uvx pip install pycparser
```

## 🚀 Usage

1.  **Run the script**:
    ```bash
    python src/cbor_codegen.py <your_header_file.h> --output-dir <output_directory> [--generate-json-helpers]
    ```
    Example:
    ```bash
    # Generate CBOR code for my_data.h into the 'generated_cbor' directory
    python src/cbor_codegen.py tests/my_data.h --output-dir ./generated_cbor

    # Using uvx for a clean execution environment:
    uvx python src/cbor_codegen.py tests/my_data.h --output-dir ./generated_cbor
    ```

    This will create a directory (e.g., `generated_cbor`) containing `cbor_generated.h`, `cbor_generated.c`, and a `CMakeLists.txt` file.

2.  **Integrate with your CMake project**:
    Add the generated directory to your `CMakeLists.txt`:
    ```cmake
    add_subdirectory(generated_cbor)
    target_link_libraries(your_app PRIVATE cbor_generated tinycbor)
    ```

---

## ⚠️ Assumptions and Limitations

*   **C Preprocessing**: For complex header files with many `#include` directives or macros, it's recommended to preprocess the header first (e.g., using `gcc -E your_header.h`) and then pass the preprocessed output to `cbor-from-c`.
*   **Memory Management for Pointers**: For `char*` and other pointer types during decoding, the generated C code **does not** perform dynamic memory allocation (`malloc`). It assumes that the pointer members in your struct are already pointing to sufficiently large, allocated buffers. You are responsible for managing this memory.
*   **Unsupported C Constructs**:
    *   `union` types are not supported.
    *   Function pointers are detected but skipped.
    *   Multi-dimensional arrays beyond the first dimension are not fully supported for complex types.
    *   Flexible array members are not supported.
*   **Error Handling**: The generated C functions return `false` on any CBOR encoding/decoding error.
*   **CBOR Map Keys**: Struct member names are used directly as CBOR map keys (text strings).
*   **Anonymous Structs**: Anonymous struct definitions that are not part of a `typedef` or a named member are skipped.

---

## 🤝 Contributing

We welcome contributions! Feel free to open issues or pull requests on our GitHub repository: [jvishnefske/cbor-from-c](https://github.com/jvishnefske/cbor-from-c)

## 📄 License

This project is licensed under the [BSD 3-Clause License](LICENSE).
