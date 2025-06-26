import pytest
import cppyy
import os
from pycparser import c_parser, c_ast
from src.cbor_codegen import generate_cbor_code_for_struct, _find_struct, _find_typedef, _expand_in_place, _extract_base_type_info
import logging
import subprocess # Added for running cmake
import shutil     # Added for cleaning up directories
import tempfile   # Added for creating temporary directories

logger = logging.getLogger(__name__)

@pytest.fixture(autouse=True)
def disable_logging(caplog):
    # Disable logging during tests to avoid cluttering output
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)

@pytest.fixture(scope="session")
def cmake_build_dir():
    """
    Fixture to run CMake configuration and build in a temporary directory.
    This ensures tinycbor is downloaded and built, and its paths are available.
    """
    # Determine the project root (one level up from the tests directory)
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
    # Create a temporary directory for the build
    build_path = tempfile.mkdtemp(prefix="cbor_codegen_build_")
    
    logger.info(f"Created temporary CMake build directory: {build_path}")
    logger.info(f"Running CMake configuration for source: {project_root}")

    try:
        # Run CMake to configure the project
        subprocess.run(
            ["cmake", "-B", build_path, "-S", project_root],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"CMake configuration successful in {build_path}")

        # Run CMake to build the project (this will build tinycbor)
        subprocess.run(
            ["cmake", "--build", build_path],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"CMake build successful in {build_path}")

        # Determine tinycbor's include and library paths within the build directory
        # These paths are specific to how FetchContent and tinycbor structure their output.
        # Adjust if your CMake setup places them differently.
        tinycbor_include_path = os.path.join(build_path, "_deps", "tinycbor-src", "src")
        # tinycbor library is usually in _deps/tinycbor-build/src/
        # The actual library file name might vary (e.g., libtinycbor.a, tinycbor.lib)
        # For cppyy, adding the directory is usually sufficient for static libs.
        tinycbor_lib_path = os.path.join(build_path, "_deps", "tinycbor-build", "src")

        # Add these paths to cppyy's search paths
        cppyy.add_include_path(tinycbor_include_path)
        cppyy.add_library_path(tinycbor_lib_path)
        logger.info(f"Added tinycbor include path to cppyy: {tinycbor_include_path}")
        logger.info(f"Added tinycbor library path to cppyy: {tinycbor_lib_path}")

        # Yield the path to the build directory
        yield build_path
        
    except subprocess.CalledProcessError as e:
        logger.error(f"CMake operation failed: {e}")
        logger.error(f"STDOUT:\n{e.stdout}")
        logger.error(f"STDERR:\n{e.stderr}")
        pytest.fail(f"CMake operation failed: {e}")
    finally:
        # Clean up the temporary directory
        logger.info(f"Cleaning up temporary CMake build directory: {build_path}")
        shutil.rmtree(build_path)


# Configure cppyy to find the header file
# Assuming the script is run from the repo root or tests directory
cppyy.add_include_path(os.path.join(os.path.dirname(__file__), '..')) # Add repo root
cppyy.add_include_path(os.path.dirname(__file__)) # Add tests directory
cppyy.include("my_data.h") # Include the struct definitions from tests/my_data.h

def parse_c_string(c_code_string):
    parser = c_parser.CParser()
    return parser.parse(c_code_string, filename='<anon>')

def test_find_struct_exists():
    c_code = "struct MyStruct { int a; };"
    ast = parse_c_string(c_code)
    struct_node = _find_struct("MyStruct", ast)
    assert struct_node is not None
    assert struct_node.name == "MyStruct"

def test_find_struct_not_exists():
    c_code = "struct AnotherStruct { float b; };"
    ast = parse_c_string(c_code)
    struct_node = _find_struct("NonExistentStruct", ast)
    assert struct_node is None

def test_find_typedef_exists():
    c_code = "typedef struct { int x; } MyType;"
    ast = parse_c_string(c_code)
    typedef_node = _find_typedef("MyType", ast)
    assert typedef_node is not None
    assert typedef_node.name == "MyType"

def test_find_typedef_not_exists():
    c_code = "typedef struct { float y; } AnotherType;"
    ast = parse_c_string(c_code)
    typedef_node = _find_typedef("NonExistentType", ast)
    assert typedef_node is None

def test_expand_in_place_typedef():
    c_code = """
    typedef struct { int x; } Point;
    struct Line { Point start; Point end; };
    """
    file_ast = parse_c_string(c_code)
    line_struct = _find_struct("Line", file_ast)
    assert line_struct is not None

    # Before expansion, 'start' and 'end' are TypeDecl with 'Point' as type
    assert line_struct.decls[0].type.type.names[0] == 'Point'

    _expand_in_place(line_struct, file_ast)

    # After expansion, 'start' and 'end' should be Struct with 'Point' name
    assert isinstance(line_struct.decls[0].type.type, c_ast.Struct)
    assert line_struct.decls[0].type.type.name == 'Point'
    assert isinstance(line_struct.decls[1].type.type, c_ast.Struct)
    assert line_struct.decls[1].type.type.name == 'Point'

def test_expand_in_place_nested_struct():
    c_code = """
    struct Inner { int i; };
    struct Outer { struct Inner inner_field; };
    """
    file_ast = parse_c_string(c_code)
    outer_struct = _find_struct("Outer", file_ast)
    assert outer_struct is not None

    # Before expansion, 'inner_field' is Struct with 'Inner' name
    assert isinstance(outer_struct.decls[0].type.type, c_ast.Struct)
    assert outer_struct.decls[0].type.type.name == 'Inner'

    # Expansion should not change already defined structs, but ensure it doesn't break
    _expand_in_place(outer_struct, file_ast)

    # Should still be Struct with 'Inner' name
    assert isinstance(outer_struct.decls[0].type.type, c_ast.Struct)
    assert outer_struct.decls[0].type.type.name == 'Inner'

def test_extract_base_type_info_int():
    c_code = "struct Test { int a; };"
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Test", file_ast)
    field_node = struct_node.decls[0]
    
    type_info = _extract_base_type_info(field_node.type, file_ast)
    assert type_info['type'] == 'primitive'
    assert type_info['base_type'] == 'int'
    assert type_info['is_array'] is False
    assert type_info['array_size'] is None
    assert type_info['is_pointer'] is False
    assert type_info['is_struct'] is False
    assert type_info['struct_name'] is None

def test_extract_base_type_info_char_array():
    c_code = "struct Test { char name[64]; };"
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Test", file_ast)
    field_node = struct_node.decls[0]
    
    type_info = _extract_base_type_info(field_node.type, file_ast)
    assert type_info['type'] == 'char_array'
    assert type_info['base_type'] == 'char'
    assert type_info['is_array'] is True
    assert type_info['array_size'] == 64
    assert type_info['is_pointer'] is False
    assert type_info['is_struct'] is False
    assert type_info['struct_name'] is None

def test_extract_base_type_info_pointer_char():
    c_code = "struct Test { char* email; };"
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Test", file_ast)
    field_node = struct_node.decls[0]
    
    type_info = _extract_base_type_info(field_node.type, file_ast)
    assert type_info['type'] == 'pointer'
    assert type_info['base_type'] == 'char'
    assert type_info['is_array'] is False
    assert type_info['array_size'] is None
    assert type_info['is_pointer'] is True
    assert type_info['is_struct'] is False
    assert type_info['struct_name'] is None

def test_extract_base_type_info_nested_struct():
    c_code = """
    struct Point { int x; float y; };
    struct Test { struct Point location; };
    """
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Test", file_ast)
    field_node = struct_node.decls[0]
    
    type_info = _extract_base_type_info(field_node.type, file_ast)
    assert type_info['type'] == 'struct'
    assert type_info['base_type'] == 'struct' # Indicates it's a struct type
    assert type_info['is_array'] is False
    assert type_info['array_size'] is None
    assert type_info['is_pointer'] is False
    assert type_info['is_struct'] is True
    assert type_info['struct_name'] == 'Point'
    assert len(type_info['members']) == 2
    assert type_info['members'][0]['name'] == 'x'
    assert type_info['members'][1]['name'] == 'y'


# Test for simple struct generation
# This test uses the cmake_build_dir fixture to ensure cbor.h is found.
def test_generate_cbor_code_for_simple_struct(cmake_build_dir):
    c_code = """
    #include <stdbool.h> // For 'bool'
    struct Simple { int a; };
    """
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Simple", file_ast)
    assert struct_node is not None

    generated_encode_code, encode_prototype = generate_cbor_code_for_struct(struct_node, file_ast)

    # Compile and test the generated code using cppyy
    full_c_code = f"""
    #include <stdint.h>
    #include <stdbool.h>
    #include <string.h>
    #include <stdio.h> // For debugging printfs if any
    #include <cbor.h> // cbor.h is now found via cmake_build_dir fixture

    // The struct definition for this test
    struct Simple {{ int a; }};

    // The generated CBOR encoding function
    {generated_encode_code}

    // Wrapper function to encode into a buffer and return length
    size_t test_encode_Simple_wrapper(const struct Simple* data, uint8_t* buffer, size_t buffer_size) {{
        CborEncoder encoder;
        cbor_encoder_init(&encoder, buffer, buffer_size, 0);
        cbor_encode_Simple(&encoder, data);
        return cbor_encoder_get_buffer_size(&encoder, buffer);
    }}
    """
    cppyy.cppdef(full_c_code)

    # Access the compiled struct and functions
    Simple = cppyy.gbl.Simple
    test_encode_Simple_wrapper = cppyy.gbl.test_encode_Simple_wrapper

    # Test encoding
    original_simple = Simple()
    original_simple.a = 42

    buffer_size = 100
    buffer = cppyy.gbl.new_array(cppyy.gbl.uint8_t, buffer_size)

    encoded_len = test_encode_Simple_wrapper(original_simple, buffer, buffer_size)
    assert encoded_len > 0
    assert encoded_len <= buffer_size

    # Clean up the buffer
    cppyy.gbl.delete_array(buffer)


# Test for struct with nested struct and arrays
# This test uses the cmake_build_dir fixture to ensure cbor.h is found.
def test_generate_cbor_code_for_struct_with_nested_struct(cmake_build_dir):
    # The Person struct is defined in tests/my_data.h, which is included via cppyy.include
    # We need to parse a dummy C code string to get the AST for Person,
    # as the actual struct definition is in my_data.h
    c_code = """
    #include "my_data.h" // Include the actual header for struct definitions
    // Dummy struct definition to get AST node for Person
    struct Person {
        char name[64];
        int age;
        bool is_student;
        Point location; // Nested struct
        int scores[5]; // Array of integers
        char* email; // Pointer to char (string)
        uint64_t id;
        double balance;
        struct Address address; // Nested struct defined above
        char notes[256]; // Added from my_data.h
        int* favorite_number; // Added from my_data.h
    };
    """
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Person", file_ast)
    assert struct_node is not None

    generated_encode_code, encode_prototype = generate_cbor_code_for_struct(struct_node, file_ast)

    # Compile and test the generated code using cppyy
    # my_data.h is already included globally by cppyy.include at the top of the file
    full_c_code = f"""
    #include <stdint.h>
    #include <stdbool.h>
    #include <string.h>
    #include <stdio.h> // For debugging printfs if any
    #include <stdlib.h> // For malloc/free if needed by dummy decoder
    #include <cbor.h> // cbor.h is now found via cmake_build_dir fixture
    #include "my_data.h" // Include the actual header for struct definitions

    // The generated CBOR encoding function for Person
    {generated_encode_code}

    // Wrapper function to encode into a buffer and return length
    size_t test_encode_Person_wrapper(const struct Person* data, uint8_t* buffer, size_t buffer_size) {{
        CborEncoder encoder;
        cbor_encoder_init(&encoder, buffer, buffer_size, 0);
        cbor_encode_Person(&encoder, data);
        return cbor_encoder_get_buffer_size(&encoder, buffer);
    }}
    """
    cppyy.cppdef(full_c_code)

    # Access the compiled structs and functions
    Person = cppyy.gbl.Person
    Point = cppyy.gbl.Point
    Address = cppyy.gbl.Address
    strcpy = cppyy.gbl.strcpy # For char arrays
    
    test_encode_Person_wrapper = cppyy.gbl.test_encode_Person_wrapper

    # Test encoding
    original_person = Person()
    strcpy(original_person.name, "Alice Smith")
    original_person.age = 30
    original_person.is_student = True
    original_person.location.x = 10
    original_person.location.y = 20.5
    original_person.scores[0] = 100
    original_person.scores[1] = 90
    original_person.scores[2] = 80
    original_person.scores[3] = 70
    original_person.scores[4] = 60
    original_person.email = "alice@example.com" # cppyy handles this by creating a C string literal
    original_person.id = 1234567890123456789
    original_person.balance = 12345.6789

    strcpy(original_person.address.street, "123 Main St")
    original_person.address.number = 123
    strcpy(original_person.address.city, "Anytown")
    strcpy(original_person.notes, "Some notes about Alice.")
    original_person.favorite_number = cppyy.gbl.new_array(cppyy.gbl.int, 1)
    original_person.favorite_number[0] = 77

    buffer_size = 1024 # Larger buffer for complex struct
    buffer = cppyy.gbl.new_array(cppyy.gbl.uint8_t, buffer_size)

    encoded_len = test_encode_Person_wrapper(original_person, buffer, buffer_size)
    assert encoded_len > 0
    assert encoded_len <= buffer_size

    # Clean up the buffer
    cppyy.gbl.delete_array(buffer)
    cppyy.gbl.delete_array(original_person.favorite_number) # Clean up original's allocated pointer


# Test for empty struct generation
# This test uses the cmake_build_dir fixture to ensure cbor.h is found.
def test_generate_cbor_code_for_empty_struct(cmake_build_dir):
    # The EmptyStruct is defined in tests/my_data.h, which is included via cppyy.include
    c_code = "struct EmptyStruct {};"
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("EmptyStruct", file_ast)
    assert struct_node is not None

    generated_encode_code, encode_prototype = generate_cbor_code_for_struct(struct_node, file_ast)

    # Compile and test the generated code using cppyy
    full_c_code = f"""
    #include <stdint.h>
    #include <stdbool.h>
    #include <string.h>
    #include <stdio.h> // For debugging printfs if any
    #include <cbor.h> // cbor.h is now found via cmake_build_dir fixture
    #include "my_data.h" // Include the actual header for struct definitions

    // The generated CBOR encoding function for EmptyStruct
    {generated_encode_code}

    // Wrapper function to encode into a buffer and return length
    size_t test_encode_EmptyStruct_wrapper(const struct EmptyStruct* data, uint8_t* buffer, size_t buffer_size) {{
        CborEncoder encoder;
        cbor_encoder_init(&encoder, buffer, buffer_size, 0);
        cbor_encode_EmptyStruct(&encoder, data);
        return cbor_encoder_get_buffer_size(&encoder, buffer);
    }}
    """
    cppyy.cppdef(full_c_code)

    # Access the compiled struct and functions
    EmptyStruct = cppyy.gbl.EmptyStruct
    test_encode_EmptyStruct_wrapper = cppyy.gbl.test_encode_EmptyStruct_wrapper

    # Test encoding
    original_empty = EmptyStruct()

    buffer_size = 100
    buffer = cppyy.gbl.new_array(cppyy.gbl.uint8_t, buffer_size)

    encoded_len = test_encode_EmptyStruct_wrapper(original_empty, buffer, buffer_size)
    assert encoded_len > 0 # Even empty structs might have a minimal CBOR representation (e.g., map of 0 items)
    assert encoded_len <= buffer_size

    # Clean up the buffer
    cppyy.gbl.delete_array(buffer)
