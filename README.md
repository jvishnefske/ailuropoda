<p align="center">
  <a href="https://github.com/jvishnefske/Ailuropoda">
    <img src="https://img.shields.io/badge/Project-Ailuropoda-blueviolet?style=for-the-badge&logo=github" alt="Project Badge">
  </a>
  <a href="https://github.com/jvishnefske/Ailuropoda/actions/workflows/ci.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/jvishnefske/Ailuropoda/ci.yml?branch=main&style=for-the-badge&logo=githubactions&label=CI%20Build" alt="CI Build Status">
  </a>
  <img src="https://img.shields.io/badge/Python-3.8+-blue?style=for-the-badge&logo=python" alt="Python Version">
  <a href="https://github.com/jvishnefske/Ailuropoda/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge" alt="License: MIT">
  </a>
</p>

# 🐼 Ailuropoda: Automate CBOR for C Structs

## ✨ Tired of writing tedious, error-prone boilerplate C code for CBOR serialization and deserialization?

**`Ailuropoda`** is your solution! This powerful Python tool automatically generates robust C functions to encode and decode your C structs into Concise Binary Object Representation (CBOR), seamlessly integrating with the TinyCBOR library.

---

## 🚀 Why `Ailuropoda`?

Manually handling CBOR for complex C data structures is a time sink. `Ailuropoda` eliminates this pain, letting you focus on your core logic while it handles the serialization boilerplate.

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
    *   Fixed-size arrays of primitive types or nested structs.
*   **Ready-to-Use Output**: Generates a dedicated output directory containing:
    *   `cbor_generated.h` and `cbor_generated.c` with your encode/decode functions.
    *   A `CMakeLists.txt` file to easily compile the generated code and link against TinyCBOR.
    *   Helper functions for `cbor2json` and `json2cbor` conversion, simplifying data inspection and interoperability.
*   **Simplified Development**: Define your data structures in C headers, and let `Ailuropoda` handle the rest!
 
---

## 🛠️ How It Works

`Ailuropoda` leverages `pycparser` to parse your C header file's Abstract Syntax Tree (AST). It identifies `struct` definitions and their members, then intelligently generates the corresponding C encoding and decoding functions.

---

## 📦 Installation & Setup

```bash
# First, install uv (if you haven't already):
curl -LsSf https://astral.sh/uv/install.sh | sh

# Navigate to your project directory
cd /path/to/Ailuropoda

# Create and synchronize the virtual environment with core dependencies
uv sync
```

### For Development & Testing

```bash
# Install development dependencies (including pytest, pytest-subprocess, etc.)
uv sync --dev
```

## 🚀 Usage

1.  **Run the script**:
    ```bash
    uv run python src/cbor_codegen.py <your_header_file.h> --output-dir <output_directory> [--generate-json-helpers]
    ```
    Example:
    ```bash
    # Generate CBOR code for my_data.h into the 'generated_cbor' directory
    uv run python src/cbor_codegen.py tests/my_data.h --output-dir ./generated_cbor

    # Using uvx for a clean execution environment:
    # (Note: uvx is typically used for ad-hoc commands. For project work, `uv run` is preferred.)
    # uvx python src/cbor_codegen.py tests/my_data.h --output-dir ./generated_cbor
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

*   **C Preprocessing**: For complex header files with many `#include` directives or macros, it's recommended to preprocess the header first (e.g., using `gcc -E your_header.h`) and then pass the preprocessed output to `Ailuropoda`.
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

## 💡 Development & Testing Insights

### Python Environment and Project Configuration

`Ailuropoda` follows modern Python packaging and dependency management best practices, leveraging `uv` and `pyproject.toml`.

*   **`pyproject.toml` (PEP 621)**: This file serves as the single source of truth for project metadata, dependencies, and build system configuration. It adheres to PEP 621, making the project easily discoverable and installable by tools like `pip`, `uv`, or `rye`.
*   **`uv` for Virtual Environments**: `uv` is used for fast dependency resolution and virtual environment management. Commands like `uv sync` ensure all project dependencies (and development dependencies with `--dev`) are installed into an isolated virtual environment.
*   **Running Scripts**: Always use `uv run python <script_path>` (or `uv run <module_name>`) to execute project scripts. This automatically activates the virtual environment and ensures the correct Python interpreter and installed packages are used. This approach eliminates the need for manual `source .venv/bin/activate` or manipulating the `PATH` environment variable, promoting a cleaner and more reliable development workflow.

### C/C++ Integration Testing with Pytest

The project includes robust integration tests (`tests/integration/test_full_pipeline.py`) to ensure the entire code generation, compilation, and execution pipeline works as expected.

*   **Pytest Fixtures**: Pytest fixtures are extensively used to set up and tear down the testing environment:
    *   `tmp_path`: Provides a unique, temporary directory for each test, ensuring isolation and preventing test interference. All generated files (C code, build artifacts) are placed here.
    *   `tinycbor_install_path`: This fixture handles the compilation and installation of the `TinyCBOR` C library, which `Ailuropoda`'s generated code depends on. It ensures `TinyCBOR` is available in a known location for subsequent compilation steps.
    *   `setup_test_environment`: This orchestrates the core integration steps:
        1.  It calls `ailuropoda.cbor_codegen.generate_cbor_code` to generate the `cbor_generated.h`, `cbor_generated.c`, and `CMakeLists.txt` files into the `tmp_path`.
        2.  It then uses `subprocess` to invoke `cmake` and `make` within the generated directory to compile the generated C code, linking it against the `TinyCBOR` library.
        3.  Finally, it compiles a simple C test harness (e.g., `c_test_harness_simple_data.c.jinja`) that uses the generated CBOR functions, creating an executable binary.
*   **`subprocess` Module**: Python's `subprocess` module is used to execute external commands, such as `cmake`, `make`, and the compiled C test binaries. This allows the Python tests to drive the C build and execution process.
*   **Verification**: After execution, the tests can read the output of the C binary (e.g., serialized CBOR data, deserialized values) and compare it against expected results, ensuring correctness of the generated code.

This setup provides a comprehensive way to validate `Ailuropoda`'s output and its compatibility with the target C environment.

---

## 🤝 Contributing

We welcome contributions! Feel free to open issues or pull requests on our GitHub repository: [jvishnefske/Ailuropoda](https://github.com/jvishnefske/Ailuropoda)

## 📄 License

This project is licensed under the [BSD 3-Clause License](LICENSE).

---

## 🚧 TODO / Future Enhancements

We're continuously working to improve `Ailuropoda`. Here are some planned features:

*   **CBOR to JSON / JSON to CBOR Helpers**: Implement optional C helper functions for converting between CBOR and JSON, simplifying debugging and interoperability.
*   **Dynamic Memory Management for Pointers**: Enhance `char*` and other pointer decoding to optionally handle dynamic memory allocation (`malloc`/`free`) for decoded data, reducing the burden on the user.
*   **Union Type Support**: Add support for C `union` types.
*   **Enum Type Support**: Generate appropriate CBOR representations for C `enum` types.
*   **Improved Error Handling**: Provide more granular error codes and messages in the generated C functions.
*   **Advanced Array Support**: Explore support for multi-dimensional arrays and flexible array members.
