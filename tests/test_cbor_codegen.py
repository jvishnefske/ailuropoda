# tests/test_cbor_codegen.py

import pytest
import sys
import os
from pycparser import c_parser, c_ast, parse_file

# Add the src directory to the Python path to allow importing modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from cbor_codegen import (
    _find_struct,
    _find_typedef,
    _expand_in_place,
    _extract_base_type_info,
    generate_cbor_code_for_struct,
    logger # Import the logger to potentially suppress its output during tests
)

# Suppress logging output during tests for cleaner test results
@pytest.fixture(autouse=True)
def disable_logging(caplog):
    caplog.set_level(100) # Set to a very high level to suppress all messages
    yield
    caplog.set_level(0) # Reset after test

# Helper function to parse a C string into a FileAST
def parse_c_string(c_code_string):
    parser = c_parser.CParser()
    return parser.parse(c_code_string, filename='<test_code>')

# --- Tests for _find_struct ---
def test_find_struct_exists():
    c_code = """
    struct MyStruct { int x; };
    struct AnotherStruct { float y; };
    """
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("MyStruct", file_ast)
    assert struct_node is not None
    assert struct_node.name == "MyStruct"

def test_find_struct_not_exists():
    c_code = """
    struct MyStruct { int x; };
    """
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("NonExistentStruct", file_ast)
    assert struct_node is None

# --- Tests for _find_typedef ---
def test_find_typedef_exists():
    c_code = """
    typedef struct { int x; } MyTypedefStruct;
    typedef int MyInt;
    """
    file_ast = parse_c_string(c_code)
    typedef_node = _find_typedef("MyTypedefStruct", file_ast)
    assert typedef_node is not None
    assert typedef_node.name == "MyTypedefStruct"

def test_find_typedef_not_exists():
    c_code = """
    typedef int MyInt;
    """
    file_ast = parse_c_string(c_code)
    typedef_node = _find_typedef("NonExistentTypedef", file_ast)
    assert typedef_node is None

# --- Tests for _expand_in_place ---
def test_expand_in_place_typedef():
    c_code = """
    typedef int MyInt;
    struct TestStruct { MyInt value; };
    """
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("TestStruct", file_ast)
    assert struct_node is not None
    
    # Before expansion, 'value' type is a TypeDecl with a IdentifierType 'MyInt'
    value_decl = struct_node.decls[0]
    assert isinstance(value_decl.type, c_ast.TypeDecl)
    assert isinstance(value_decl.type.type, c_ast.IdentifierType)
    assert value_decl.type.type.names == ['MyInt']

    _expand_in_place(struct_node, file_ast)

    # After expansion, 'value' type should be a TypeDecl with a IdentifierType 'int'
    value_decl_expanded = struct_node.decls[0]
    assert isinstance(value_decl_expanded.type, c_ast.TypeDecl)
    assert isinstance(value_decl_expanded.type.type, c_ast.IdentifierType)
    assert value_decl_expanded.type.type.names == ['int']

def test_expand_in_place_nested_struct():
    c_code = """
    struct Inner { int i; };
    struct Outer { struct Inner inner_field; };
    """
    file_ast = parse_c_string(c_code)
    outer_struct_node = _find_struct("Outer", file_ast)
    assert outer_struct_node is not None

    # Before expansion, 'inner_field' type is a TypeDecl with a Struct 'Inner'
    inner_field_decl = outer_struct_node.decls[0]
    assert isinstance(inner_field_decl.type, c_ast.TypeDecl)
    assert isinstance(inner_field_decl.type.type, c_ast.Struct)
    assert inner_field_decl.type.type.name == 'Inner'
    assert inner_field_decl.type.type.decls is None # Should be None if not expanded

    _expand_in_place(outer_struct_node, file_ast)

    # After expansion, 'inner_field' type should be a TypeDecl with a Struct 'Inner'
    # and its 'decls' should be populated
    inner_field_decl_expanded = outer_struct_node.decls[0]
    assert isinstance(inner_field_decl_expanded.type, c_ast.TypeDecl)
    assert isinstance(inner_field_decl_expanded.type.type, c_ast.Struct)
    assert inner_field_decl_expanded.type.type.name == 'Inner'
    assert inner_field_decl_expanded.type.type.decls is not None
    assert len(inner_field_decl_expanded.type.type.decls) == 1
    assert inner_field_decl_expanded.type.type.decls[0].name == 'i'

# --- Tests for _extract_base_type_info ---
def test_extract_base_type_info_int():
    c_code = "struct S { int x; };"
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("S", file_ast)
    int_type_node = struct_node.decls[0].type
    info = _extract_base_type_info(int_type_node, file_ast)
    assert info == {'type': 'primitive', 'base_type': 'int', 'is_array': False, 'array_len': None}

def test_extract_base_type_info_char_array():
    c_code = "struct S { char name[64]; };"
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("S", file_ast)
    array_type_node = struct_node.decls[0].type
    info = _extract_base_type_info(array_type_node, file_ast)
    assert info == {'type': 'char_array', 'base_type': 'char', 'is_array': True, 'array_len': 64}

def test_extract_base_type_info_pointer_char():
    c_code = "struct S { char* email; };"
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("S", file_ast)
    pointer_type_node = struct_node.decls[0].type
    info = _extract_base_type_info(pointer_type_node, file_ast)
    assert info == {'type': 'pointer', 'base_type': 'char', 'is_array': False, 'array_len': None}

def test_extract_base_type_info_nested_struct():
    c_code = """
    struct Point { int x; float y; };
    struct Person { struct Point location; };
    """
    file_ast = parse_c_string(c_code)
    person_struct_node = _find_struct("Person", file_ast)
    # Expand the struct first to get the full definition
    _expand_in_place(person_struct_node, file_ast)
    nested_struct_type_node = person_struct_node.decls[0].type
    info = _extract_base_type_info(nested_struct_type_node, file_ast)
    assert info['type'] == 'struct'
    assert info['base_type'] == 'Point'
    assert info['is_array'] == False
    assert info['array_len'] is None
    assert len(info['members']) == 2
    assert info['members'][0]['name'] == 'x'
    assert info['members'][1]['name'] == 'y'

# --- Tests for generate_cbor_code_for_struct ---
def test_generate_cbor_code_for_simple_struct():
    c_code = """
    struct Simple {
        int a;
        float b;
        bool c;
    };
    """
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Simple", file_ast)
    generated_code = generate_cbor_code_for_struct(struct_node, file_ast)

    assert "int a;" in generated_code
    assert "float b;" in generated_code
    assert "bool c;" in generated_code
    assert "cbor_encode_int(&map_encoder, data->a);" in generated_code
    assert "cbor_encode_float(&map_encoder, data->b);" in generated_code
    assert "cbor_encode_boolean(&map_encoder, data->c);" in generated_code
    assert "cbor_encode_map_start(encoder, &map_encoder, 3);" in generated_code # 3 members

def test_generate_cbor_code_for_struct_with_array_and_string():
    c_code = """
    struct Complex {
        char name[64];
        int scores[5];
        char* email;
    };
    """
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Complex", file_ast)
    generated_code = generate_cbor_code_for_struct(struct_node, file_ast)

    assert "char name[64];" in generated_code
    assert "int scores[5];" in generated_code
    assert "char* email;" in generated_code

    assert "cbor_encode_text_string(&map_encoder, data->name, strlen(data->name));" in generated_code
    assert "cbor_encode_array_start(&map_encoder, &map_encoder, 5);" in generated_code
    assert "for (size_t i = 0; i < 5; ++i) { cbor_encode_int(&map_encoder, data->scores[i]); }" in generated_code
    assert "cbor_encode_text_string(&map_encoder, data->email, strlen(data->email));" in generated_code
    assert "cbor_encode_map_start(encoder, &map_encoder, 3);" in generated_code # 3 members

def test_generate_cbor_code_for_struct_with_nested_struct():
    c_code = """
    struct Point { int x; float y; };
    struct Person {
        char name[64];
        struct Point location;
    };
    """
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("Person", file_ast)
    generated_code = generate_cbor_code_for_struct(struct_node, file_ast)

    assert "char name[64];" in generated_code
    assert "struct Point location;" in generated_code
    assert "cbor_encode_text_string(&map_encoder, data->name, strlen(data->name));" in generated_code
    assert "cbor_encode_Point(&map_encoder, &data->location);" in generated_code # Expect call to nested encoder
    assert "cbor_encode_map_start(encoder, &map_encoder, 2);" in generated_code # 2 members

    # Also check that the nested struct's encoder function is generated
    point_struct_node = _find_struct("Point", file_ast)
    generated_point_code = generate_cbor_code_for_struct(point_struct_node, file_ast)
    assert "void cbor_encode_Point(CborEncoder* encoder, const struct Point* data)" in generated_point_code
    assert "cbor_encode_int(&map_encoder, data->x);" in generated_point_code
    assert "cbor_encode_float(&map_encoder, data->y);" in generated_point_code

def test_generate_cbor_code_for_empty_struct():
    c_code = """
    struct EmptyStruct {};
    """
    file_ast = parse_c_string(c_code)
    struct_node = _find_struct("EmptyStruct", file_ast)
    generated_code = generate_cbor_code_for_struct(struct_node, file_ast)

    assert "void cbor_encode_EmptyStruct(CborEncoder* encoder, const struct EmptyStruct* data)" in generated_code
    assert "cbor_encode_map_start(encoder, &map_encoder, 0);" in generated_code
    assert "/* No members to encode */" in generated_code
