# Ailuropoda Design Document

## Purpose

Ailuropoda is a Python tool that automatically generates CBOR (Concise Binary Object Representation) encode and decode C functions from C header files containing struct definitions. This eliminates manual, error-prone boilerplate code for serialization/deserialization.

## Architecture Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   C Header      │────▶│   pycparser     │────▶│   Jinja2        │
│   (.h file)     │     │   (AST Parser)  │     │   Templates     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
                                                        ▼
                                                ┌─────────────────┐
                                                │  Generated C    │
                                                │  - .h header    │
                                                │  - .c source    │
                                                │  - CMakeLists   │
                                                └─────────────────┘
```

### Components

1. **Input Parser (pycparser)**: Parses C header files into an Abstract Syntax Tree (AST)
2. **Code Generator (cbor_codegen.py)**: Traverses AST to identify structs and generate encode/decode functions
3. **Template Engine (Jinja2)**: Renders C code from templates for consistent output formatting
4. **Output Generator**: Produces ready-to-compile C files with CMake integration

### Data Flow

1. User provides C header file with struct definitions
2. pycparser parses header into AST
3. Code generator extracts struct definitions and member types
4. For each struct, generates `encode_<StructName>()` and `decode_<StructName>()` functions
5. Outputs `cbor_generated.h`, `cbor_generated.c`, and `CMakeLists.txt`

## MVP Functional Requirements

### Core Generation (FR-CORE)

- [ ] **FR-CORE-01**: Parse C header files containing struct definitions
  - Test: `test_cbor_codegen.py::test_parse_simple_struct`

- [ ] **FR-CORE-02**: Generate `encode_<StructName>()` function for each struct
  - Test: `test_cbor_codegen.py::test_generate_encoder`

- [ ] **FR-CORE-03**: Generate `decode_<StructName>()` function for each struct
  - Test: `test_cbor_codegen.py::test_generate_decoder`

- [ ] **FR-CORE-04**: Output compilable C code compatible with TinyCBOR library
  - Test: `tests/integration/test_full_pipeline.py`

### Type Support (FR-TYPE)

- [ ] **FR-TYPE-01**: Support basic integer types (int, uint8_t, int32_t, uint64_t, etc.)
  - Test: `test_cbor_codegen.py::test_integer_types`

- [ ] **FR-TYPE-02**: Support floating-point types (float, double)
  - Test: `test_cbor_codegen.py::test_float_types`

- [ ] **FR-TYPE-03**: Support boolean type (bool)
  - Test: `test_cbor_codegen.py::test_bool_type`

- [ ] **FR-TYPE-04**: Support fixed-size character arrays (char name[64])
  - Test: `test_cbor_codegen.py::test_char_array`

- [ ] **FR-TYPE-05**: Support character pointers (char*, const char*)
  - Test: `test_cbor_codegen.py::test_char_pointer`

- [ ] **FR-TYPE-06**: Support nested structs
  - Test: `test_cbor_codegen.py::test_nested_struct`

- [ ] **FR-TYPE-07**: Support fixed-size arrays of primitives
  - Test: `test_cbor_codegen.py::test_primitive_array`

### Build Integration (FR-BUILD)

- [ ] **FR-BUILD-01**: Generate CMakeLists.txt for output directory
  - Test: Verify CMakeLists.txt exists in output

- [ ] **FR-BUILD-02**: Generated CMake correctly links against TinyCBOR
  - Test: `tests/integration/test_full_pipeline.py`

### CLI Interface (FR-CLI)

- [ ] **FR-CLI-01**: Accept input header file path as argument
  - Test: `test_cbor_codegen.py::test_cli_input`

- [ ] **FR-CLI-02**: Accept `--output-dir` option for output directory
  - Test: `test_cbor_codegen.py::test_cli_output_dir`

- [ ] **FR-CLI-03**: Return non-zero exit code on error
  - Test: `test_cbor_codegen.py::test_cli_error_handling`

### Error Handling (FR-ERR)

- [ ] **FR-ERR-01**: Return false from generated functions on CBOR encoding errors
  - Test: Integration test with malformed data

- [ ] **FR-ERR-02**: Skip unsupported constructs (unions, function pointers) with warnings
  - Test: `test_cbor_codegen.py::test_skip_unsupported`

## Non-Functional Requirements

- **NFR-01**: Generated code must compile without warnings with `-Wall -Wextra`
- **NFR-02**: Python package installable via pip from PyPI
- **NFR-03**: Support Python 3.8+
- **NFR-04**: Test coverage target: 80%+

## Traceability Matrix

| Requirement | Test File | Status |
|-------------|-----------|--------|
| FR-CORE-01 | test_cbor_codegen.py | Pending |
| FR-CORE-02 | test_cbor_codegen.py | Pending |
| FR-CORE-03 | test_cbor_codegen.py | Pending |
| FR-CORE-04 | test_full_pipeline.py | Pending |
| FR-TYPE-* | test_cbor_codegen.py | Pending |
| FR-BUILD-* | test_full_pipeline.py | Pending |
| FR-CLI-* | test_cbor_codegen.py | Pending |
| FR-ERR-* | test_cbor_codegen.py | Pending |
