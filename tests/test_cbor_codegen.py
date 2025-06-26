import pytest
import os
import tempfile
import shutil
import logging
import subprocess
from pathlib import Path

# Import functions from the main script
# Assuming src/cbor_codegen.py is in the parent directory
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from cbor_codegen import (
    parse_c_string,
    _find_struct,
    _collect_struct_and_typedef_definitions,
    _get_base_type_and_modifiers,
    _get_struct_members,
    generate_cbor_code
)
from pycparser import c_ast

logger = logging.getLogger(__name__)

# Fixture to set up a temporary CMake build directory for tinycbor
# This fixture was problematic as it assumed a CMakeLists.txt at project root.
# For unit tests, we don't need a full tinycbor build.
# The full pipeline test handles the actual CMake build.
# This fixture is likely for cppyy usage, which is not strictly necessary for these unit tests.
@pytest.fixture(scope="session")
def cmake_build_dir():
    """
    Fixture to provide a dummy path.
    The unit tests in this file do not require a full CMake build of tinycbor.
    """
    # This fixture is primarily for cppyy setup, which is not directly used by the
    # functions being tested in this file (parse_c_string, _find_struct, etc.).
    # The full pipeline test handles the actual CMake build.
    # For now, return a dummy path. If cppyy is truly needed for these unit tests,
    # its setup needs to be more robust or mocked.
    yield "/tmp/dummy_build_dir" # Just a placeholder

# --- Test parsing and AST manipulation helpers ---

def test_parse_c_string_simple():
    c_code = "struct MyStruct { int a; };"
    ast = parse_c_string(c_code)
    assert isinstance(ast, c_ast.FileAST)
    assert len(ast.ext) > 0

def test_find_struct_simple():
    c_code = "struct MyStruct { int a; };"
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("MyStruct", file_ast)
    assert struct_node is not None
    assert struct_node.name == "MyStruct"

def test_find_struct_typedef():
    c_code = "typedef struct { int x; } Point;"
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Point", file_ast)
    assert struct_node is not None
    assert struct_node.name is None # Anonymous struct, name comes from typedef

def test_find_struct_not_found():
    c_code = "struct MyStruct { int a; };"
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("NonExistentStruct", file_ast)
    assert struct_node is None

def test_collect_struct_and_typedef_definitions():
    c_code = """
    struct S1 { int a; };
    typedef struct S2 { float b; } T2;
    typedef struct { char c; } T3;
    typedef S1 T1;
    """
    file_ast = parse_c_string(c_code)
    struct_defs, typedef_map = _collect_struct_and_typedef_definitions(file_ast)

    assert "S1" in struct_defs
    assert "S2" in struct_defs
    assert "T1" in typedef_map
    assert "T2" in typedef_map
    assert "T3" in typedef_map

    assert isinstance(struct_defs["S1"], c_ast.Struct)
    assert isinstance(struct_defs["S2"], c_ast.Struct)

    # T1 should resolve to S1 struct
    # The typedef_map stores the TypeDecl/IdentifierType, _get_base_type_and_modifiers resolves it to Struct
    assert isinstance(typedef_map["T1"], c_ast.IdentifierType)
    assert typedef_map["T1"].names == ['S1']

    assert isinstance(typedef_map["T2"], c_ast.TypeDecl) # T2 is a TypeDecl wrapping a Struct
    assert isinstance(typedef_map["T2"].type, c_ast.Struct)
    assert typedef_map["T2"].type.name == "S2"

    assert isinstance(typedef_map["T3"], c_ast.TypeDecl) # T3 is a TypeDecl wrapping an anonymous Struct
    assert isinstance(typedef_map["T3"].type, c_ast.Struct)
    assert typedef_map["T3"].type.name is None


def test_expand_in_place_typedef():
    # This test now checks the behavior of _get_struct_members with typedefs,
    # as _expand_in_place is no longer used for in-place AST modification.
    # The type resolution is handled by _get_base_type_and_modifiers and _get_struct_members.
    c_code = """
    typedef struct { int x; } Point;
    struct Line { Point start; Point end; };
    """
    file_ast = parse_c_string(c_code)
    struct_defs, typedef_map = _collect_struct_and_typedef_definitions(file_ast)

    line_struct = _find_struct("Line", file_ast)
    assert line_struct is not None

    members = _get_struct_members(line_struct, struct_defs, typedef_map)

    assert len(members) == 2
    assert members[0]['name'] == 'start'
    assert members[0]['type_name'] == 'anonymous_struct'
    assert members[0]['is_struct']
    assert members[0]['type_category'] == 'struct'

    assert members[1]['name'] == 'end'
    assert members[1]['type_name'] == 'anonymous_struct'
    assert members[1]['is_struct']
    assert members[1]['type_category'] == 'struct'


# --- Test _get_base_type_and_modifiers ---

def test_get_base_type_and_modifiers_int():
    c_code = "struct Test { int a; };"
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Test", file_ast)
    field_node = struct_node.decls[0]
    base_type, is_pointer, array_size = _get_base_type_and_modifiers(field_node.type, {})
    assert isinstance(base_type, c_ast.IdentifierType)
    assert ' '.join(base_type.names) == 'int'
    assert not is_pointer
    assert array_size is None

def test_get_base_type_and_modifiers_char_array():
    c_code = "struct Test { char name[64]; };"
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Test", file_ast)
    field_node = struct_node.decls[0]
    base_type, is_pointer, array_size = _get_base_type_and_modifiers(field_node.type, {})
    assert isinstance(base_type, c_ast.IdentifierType)
    assert ' '.join(base_type.names) == 'char'
    assert not is_pointer
    assert array_size == 64

def test_get_base_type_and_modifiers_pointer_char():
    c_code = "struct Test { char* email; };"
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Test", file_ast)
    field_node = struct_node.decls[0]
    base_type, is_pointer, array_size = _get_base_type_and_modifiers(field_node.type, {})
    assert isinstance(base_type, c_ast.IdentifierType)
    assert ' '.join(base_type.names) == 'char'
    assert is_pointer
    assert array_size is None

def test_get_base_type_and_modifiers_nested_struct():
    c_code = """
    struct Point { int x; float y; };
    struct Test { struct Point location; };
    """
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Test", file_ast)
    field_node = struct_node.decls[0]
    base_type, is_pointer, array_size = _get_base_type_and_modifiers(field_node.type, {})
    assert isinstance(base_type, c_ast.Struct)
    assert base_type.name == 'Point'
    assert not is_pointer
    assert array_size is None

def test_get_base_type_and_modifiers_typedef_struct():
    c_code = """
    typedef struct { int x; } Point;
    struct Test { Point p; };
    """
    file_ast = parse_c_string(c_code)
    struct_defs, typedef_map = _collect_struct_and_typedef_definitions(file_ast)
    struct_node = _find_struct("Test", file_ast)
    field_node = struct_node.decls[0]
    base_type, is_pointer, array_size = _get_base_type_and_modifiers(field_node.type, typedef_map)
    assert isinstance(base_type, c_ast.Struct)
    assert base_type.name is None # Anonymous struct
    assert not is_pointer
    assert array_size is None

def test_get_base_type_and_modifiers_typedef_pointer_to_struct():
    c_code = """
    struct MyData { int x; };
    typedef struct MyData* MyDataPtr;
    struct Test { MyDataPtr data_ptr; };
    """
    file_ast = parse_c_string(c_code)
    struct_defs, typedef_map = _collect_struct_and_typedef_definitions(file_ast)
    struct_node = _find_struct("Test", file_ast)
    field_node = struct_node.decls[0]
    base_type, is_pointer, array_size = _get_base_type_and_modifiers(field_node.type, typedef_map)
    assert isinstance(base_type, c_ast.Struct)
    assert base_type.name == 'MyData'
    assert is_pointer
    assert array_size is None


# --- Test _get_struct_members ---

def test_get_struct_members_simple():
    c_code = """
    struct SimpleData {
        int32_t id;
        char name[32];
        bool is_active;
        float temperature;
        uint8_t flags[4];
    };
    """
    file_ast = parse_c_string(c_code)
    struct_defs, typedef_map = _collect_struct_and_typedef_definitions(file_ast)
    simple_data_struct = _find_struct("SimpleData", file_ast)
    members = _get_struct_members(simple_data_struct, struct_defs, typedef_map)

    assert len(members) == 5
    assert members[0]['name'] == 'id'
    assert members[0]['type_name'] == 'int32_t'
    assert members[0]['type_category'] == 'primitive'

    assert members[1]['name'] == 'name'
    assert members[1]['type_name'] == 'char'
    assert members[1]['array_size'] == 32
    assert members[1]['type_category'] == 'char_array'

    assert members[2]['name'] == 'is_active'
    assert members[2]['type_name'] == 'bool'
    assert members[2]['type_category'] == 'primitive'

    assert members[3]['name'] == 'temperature'
    assert members[3]['type_name'] == 'float'
    assert members[3]['type_category'] == 'primitive'

    assert members[4]['name'] == 'flags'
    assert members[4]['type_name'] == 'uint8_t'
    assert members[4]['array_size'] == 4
    assert members[4]['type_category'] == 'array'

def test_get_struct_members_nested_and_pointer():
    c_code = """
    struct SimpleData { int id; };
    struct NestedData {
        struct SimpleData inner_data;
        char* description;
        int32_t value;
    };
    """
    file_ast = parse_c_string(c_code)
    struct_defs, typedef_map = _collect_struct_and_typedef_definitions(file_ast)
    nested_data_struct = _find_struct("NestedData", file_ast)
    members = _get_struct_members(nested_data_struct, struct_defs, typedef_map)

    assert len(members) == 3
    assert members[0]['name'] == 'inner_data'
    assert members[0]['type_name'] == 'SimpleData'
    assert members[0]['is_struct']
    assert members[0]['type_category'] == 'struct'

    assert members[1]['name'] == 'description'
    assert members[1]['type_name'] == 'char'
    assert members[1]['is_pointer']
    assert members[1]['type_category'] == 'char_ptr'

    assert members[2]['name'] == 'value'
    assert members[2]['type_name'] == 'int32_t'
    assert members[2]['type_category'] == 'primitive'

# --- Test full code generation (requires temporary files) ---

def test_generate_cbor_code_for_simple_struct(tmp_path):
    header_content = """
    struct MySimpleStruct {
        int id;
        char name[16];
        bool active;
    };
    """
    header_file = tmp_path / "my_simple_struct.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success
    assert (output_dir / "cbor_generated.h").exists()
    assert (output_dir / "cbor_generated.c").exists()

    generated_h = (output_dir / "cbor_generated.h").read_text()
    generated_c = (output_dir / "cbor_generated.c").read_text()

    assert "struct MySimpleStruct;" in generated_h
    assert "bool encode_MySimpleStruct" in generated_h
    assert "bool decode_MySimpleStruct" in generated_h

    assert "bool encode_MySimpleStruct" in generated_c
    assert "bool decode_MySimpleStruct" in generated_c
    assert 'cbor_encode_int(&map_encoder, data->id);' in generated_c
    assert 'encode_text_string(data->name, &map_encoder);' in generated_c
    assert 'cbor_encode_boolean(&map_encoder, data->active);' in generated_c
    assert 'decode_text_string(data->name, sizeof(data->name), &map_it);' in generated_c

def test_generate_cbor_code_for_struct_with_nested_struct(tmp_path):
    header_content = """
    struct Inner {
        int x;
    };
    struct Outer {
        struct Inner inner_field;
        char* description;
    };
    """
    header_file = tmp_path / "nested_struct.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success
    assert (output_dir / "cbor_generated.h").exists()
    assert (output_dir / "cbor_generated.c").exists()

    generated_h = (output_dir / "cbor_generated.h").read_text()
    generated_c = (output_dir / "cbor_generated.c").read_text()

    assert "struct Inner;" in generated_h
    assert "struct Outer;" in generated_h
    assert "bool encode_Inner" in generated_h
    assert "bool decode_Inner" in generated_h
    assert "bool encode_Outer" in generated_h
    assert "bool decode_Outer" in generated_h

    assert "if (!encode_Inner(&data->inner_field, &map_encoder)) return false;" in generated_c
    assert "if (!decode_Inner(&data->inner_field, &map_it)) return false;" in generated_c
    assert "if (!encode_text_string(data->description, &map_encoder)) return false;" in generated_c
    assert "if (!decode_char_ptr(&data->description, 256, &map_it)) return false;" in generated_c # Check for MAX_STRING_LEN

def test_generate_cbor_code_for_empty_struct(tmp_path):
    header_content = """
    struct EmptyStruct {};
    """
    header_file = tmp_path / "empty_struct.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success
    assert (output_dir / "cbor_generated.h").exists()
    assert (output_dir / "cbor_generated.c").exists()

    generated_h = (output_dir / "cbor_generated.h").read_text()
    generated_c = (output_dir / "cbor_generated.c").read_text()

    assert "struct EmptyStruct;" in generated_h
    assert "bool encode_EmptyStruct" in generated_h
    assert "bool decode_EmptyStruct" in generated_h

    assert "cbor_encoder_create_map(encoder, &map_encoder, 0);" in generated_c # Empty map
    assert "while (!cbor_value_at_end(&map_it))" in generated_c # Loop will be empty, but structure is there
