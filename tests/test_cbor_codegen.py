import pytest
from pycparser import c_ast
import sys
from pathlib import Path

# Add the 'src' directory to sys.path to allow importing 'ailuropoda'
# This assumes the test is run from the project root or a subdirectory
# where 'src' is a direct sibling.
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from ailuropoda.cbor_codegen import parse_c_string, find_struct, find_typedef, expand_in_place, get_type_info, generate_cbor_code
import os
import tempfile

@pytest.fixture(scope="module")
def cpp_info():
    """Fixture to provide cpp_path and cpp_args for pycparser."""
    # For unit tests, we rely on pycparser's ability to find standard headers
    # if cpp is in PATH. If not, this might need more robust system include discovery.
    return {'cpp_path': 'cpp', 'cpp_args': []}

def test_parse_c_string_with_includes(cpp_info):
    c_code = """
    #include <stdint.h>
    #include <stdbool.h>
    struct MyData {
        int32_t id;
        bool active;
    };
    """
    ast = parse_c_string(c_code, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info['cpp_args'])
    assert ast is not None
    assert isinstance(ast, c_ast.FileAST)
    # Verify that MyData struct is found
    my_struct = find_struct("MyData", ast)
    assert my_struct is not None
    assert my_struct.name == "MyData"

def test_find_struct_by_name(cpp_info):
    c_code = """
    struct MyStruct { int a; };
    typedef struct AnotherStruct { float b; } AnotherStruct_t;
    """
    ast = parse_c_string(c_code, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info[
        'cpp_args'])

    my_struct = find_struct("MyStruct", ast)
    assert my_struct is not None
    assert my_struct.name == "MyStruct"

    another_struct = find_struct("AnotherStruct", ast)
    assert another_struct is not None
    assert another_struct.name == "AnotherStruct"

def test_find_typedef_by_name(cpp_info):
    c_code = """
    typedef unsigned int uint32_t;
    typedef struct MyStruct { int a; } MyStruct_t;
    """
    ast = parse_c_string(c_code, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info[
        'cpp_args'])

    uint32_t_def = find_typedef("uint32_t", ast)
    assert uint32_t_def is not None
    assert isinstance(uint32_t_def, c_ast.Typedef)
    assert isinstance(uint32_t_def.type, c_ast.TypeDecl)
    assert isinstance(uint32_t_def.type.type, c_ast.IdentifierType)
    assert uint32_t_def.type.type.names == ['unsigned', 'int']

    my_struct_t_def = find_typedef("MyStruct_t", ast)
    assert my_struct_t_def is not None
    assert isinstance(my_struct_t_def, c_ast.Typedef)
    assert isinstance(my_struct_t_def.type, c_ast.TypeDecl)
    assert isinstance(my_struct_t_def.type.type, c_ast.Struct)
    assert my_struct_t_def.type.type.name == "MyStruct"


def test_expand_in_place_typedef_primitive(cpp_info):
    c_code = """
    typedef int MyInt;
    struct Data { MyInt value; };
    """
    ast = parse_c_string(c_code, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info[
        'cpp_args'])
    struct_node = find_struct("Data", ast)
    assert struct_node is not None

    # Before expansion, the type of 'value' should be TypeDecl -> IdentifierType('MyInt')
    member_type_before = struct_node.decls[0].type
    assert isinstance(member_type_before, c_ast.TypeDecl)
    assert isinstance(member_type_before.type, c_ast.IdentifierType)
    assert member_type_before.type.names == ['MyInt']

    # Call expand_in_place and assign the returned (modified) node
    struct_node.decls[0].type = expand_in_place(struct_node.decls[0].type, ast)

    # After expansion, the type should be TypeDecl -> IdentifierType('int')
    member_type_after = struct_node.decls[0].type
    assert isinstance(member_type_after, c_ast.TypeDecl)
    assert isinstance(member_type_after.type, c_ast.IdentifierType)
    assert member_type_after.type.names == ['int']


def test_expand_in_place_typedef_struct(cpp_info):
    c_code = """
    struct Inner { int x; };
    typedef struct Inner MyInner_t;
    struct Outer { MyInner_t nested; };
    """
    ast = parse_c_string(c_code, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info[
        'cpp_args'])
    struct_node = find_struct("Outer", ast)
    assert struct_node is not None

    # Before expansion, the type of 'nested' should be TypeDecl -> IdentifierType('MyInner_t')
    member_type_before = struct_node.decls[0].type
    assert isinstance(member_type_before, c_ast.TypeDecl)
    assert isinstance(member_type_before.type, c_ast.IdentifierType)
    assert member_type_before.type.names == ['MyInner_t']

    # Call expand_in_place and assign the returned (modified) node
    struct_node.decls[0].type = expand_in_place(struct_node.decls[0].type, ast)

    # After expansion, the type should be TypeDecl -> Struct('Inner')
    member_type_after = struct_node.decls[0].type
    assert isinstance(member_type_after, c_ast.TypeDecl)
    assert isinstance(member_type_after.type, c_ast.Struct)
    assert member_type_after.type.name == 'Inner'


def test_expand_in_place_nested_typedef_array(cpp_info):
    c_code = """
    typedef char MyChar;
    struct Data { MyChar name[16]; };
    """
    ast = parse_c_string(c_code, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info[
        'cpp_args'])
    struct_node = find_struct("Data", ast)
    assert struct_node is not None

    member_type_before = struct_node.decls[0].type
    assert isinstance(member_type_before, c_ast.ArrayDecl)
    assert isinstance(member_type_before.type, c_ast.TypeDecl)
    assert isinstance(member_type_before.type.type, c_ast.IdentifierType)
    assert member_type_before.type.type.names == ['MyChar']

    # Call expand_in_place and assign the returned (modified) node
    struct_node.decls[0].type = expand_in_place(struct_node.decls[0].type, ast)

    member_type_after = struct_node.decls[0].type
    assert isinstance(member_type_after, c_ast.ArrayDecl)
    assert isinstance(member_type_after.type, c_ast.TypeDecl)
    assert isinstance(member_type_after.type.type, c_ast.IdentifierType)
    assert member_type_after.type.type.names == ['char']


def test_get_type_info_primitive(cpp_info):
    c_code = """
    #include <stdint.h>
    #include <stdbool.h>
    struct Data {
        int id;
        uint32_t count;
        float ratio;
        bool active;
    };
    """
    ast = parse_c_string(c_code, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info[
        'cpp_args'])
    struct_node = find_struct("Data", ast)
    assert struct_node is not None
    # Ensure typedefs are expanded and assigned back
    for i, decl in enumerate(struct_node.decls):
        struct_node.decls[i].type = expand_in_place(decl.type, ast)

    members = struct_node.decls
    assert len(members) == 4

    # int id
    base_type, category, array_size, is_ptr = get_type_info(members[0].type, ast)
    assert base_type == 'int'
    assert category == 'primitive'
    assert array_size is None
    assert is_ptr is False

    # uint32_t count
    base_type, category, array_size, is_ptr = get_type_info(members[1].type, ast)
    assert base_type == 'unsigned int' # uint32_t expands to unsigned int
    assert category == 'primitive'
    assert array_size is None
    assert is_ptr is False

    # float ratio
    base_type, category, array_size, is_ptr = get_type_info(members[2].type, ast)
    assert base_type == 'float'
    assert category == 'primitive'
    assert array_size is None
    assert is_ptr is False

    # bool active
    base_type, category, array_size, is_ptr = get_type_info(members[3].type, ast)
    assert base_type == '_Bool' # bool expands to _Bool
    assert category == 'primitive'
    assert array_size is None
    assert is_ptr is False

def test_get_type_info_char_array(cpp_info):
    c_code = """
    struct Data {
        char name[32];
    };
    """
    ast = parse_c_string(c_code, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info[
        'cpp_args'])
    struct_node = find_struct("Data", ast)
    assert struct_node is not None
    for i, decl in enumerate(struct_node.decls):
        struct_node.decls[i].type = expand_in_place(decl.type, ast)

    member = struct_node.decls[0]
    base_type, category, array_size, is_ptr = get_type_info(member.type, ast)
    assert base_type == 'char'
    assert category == 'char_array'
    assert array_size == 32
    assert is_ptr is False

def test_get_type_info_char_ptr(cpp_info):
    c_code = """
    struct Data {
        char* description;
    };
    """
    ast = parse_c_string(c_code, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info[
        'cpp_args'])
    struct_node = find_struct("Data", ast)
    assert struct_node is not None
    for i, decl in enumerate(struct_node.decls):
        struct_node.decls[i].type = expand_in_place(decl.type, ast)

    member = struct_node.decls[0]
    base_type, category, array_size, is_ptr = get_type_info(member.type, ast)
    assert base_type == 'char'
    assert category == 'char_ptr'
    assert array_size is None
    assert is_ptr is True

def test_get_type_info_struct(cpp_info):
    c_code = """
    struct Inner { int x; };
    struct Outer { struct Inner nested; };
    """
    ast = parse_c_string(c_code, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info[
        'cpp_args'])
    struct_node = find_struct("Outer", ast)
    assert struct_node is not None
    for i, decl in enumerate(struct_node.decls):
        struct_node.decls[i].type = expand_in_place(decl.type, ast)

    member = struct_node.decls[0]
    base_type, category, array_size, is_ptr = get_type_info(member.type, ast)
    assert base_type == 'Inner'
    assert category == 'struct'
    assert array_size is None
    assert is_ptr is False

def test_get_type_info_struct_ptr(cpp_info):
    c_code = """
    struct Inner { int x; };
    struct Outer { struct Inner* nested_ptr; };
    """
    ast = parse_c_string(c_code, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info[
        'cpp_args'])
    struct_node = find_struct("Outer", ast)
    assert struct_node is not None
    for i, decl in enumerate(struct_node.decls):
        struct_node.decls[i].type = expand_in_place(decl.type, ast)

    member = struct_node.decls[0]
    base_type, category, array_size, is_ptr = get_type_info(member.type, ast)
    assert base_type == 'Inner'
    assert category == 'struct_ptr'
    assert array_size is None
    assert is_ptr is True

def test_get_type_info_primitive_array(cpp_info):
    c_code = """
    struct Data {
        int values[10];
    };
    """
    ast = parse_c_string(c_code, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info[
        'cpp_args'])
    struct_node = find_struct("Data", ast)
    assert struct_node is not None
    for i, decl in enumerate(struct_node.decls):
        struct_node.decls[i].type = expand_in_place(decl.type, ast)

    member = struct_node.decls[0]
    base_type, category, array_size, is_ptr = get_type_info(member.type, ast)
    assert base_type == 'int'
    assert category == 'array'
    assert array_size == 10
    assert is_ptr is False

def test_get_type_info_struct_array(cpp_info):
    c_code = """
    struct Item { int id; };
    struct Data {
        struct Item items[5];
    };
    """
    ast = parse_c_string(c_code, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info[
        'cpp_args'])
    struct_node = find_struct("Data", ast)
    assert struct_node is not None
    for i, decl in enumerate(struct_node.decls):
        struct_node.decls[i].type = expand_in_place(decl.type, ast)

    member = struct_node.decls[0]
    base_type, category, array_size, is_ptr = get_type_info(member.type, ast)
    assert base_type == 'Item'
    assert category == 'struct_array'
    assert array_size == 5
    assert is_ptr is False

def test_generate_cbor_code_for_struct_simple(tmp_path, cpp_info):
    c_code = """
    #include <stdint.h>
    #include <stdbool.h>
    struct SimpleData {
        int32_t id;
        char name[32];
        bool is_active;
    };
    """
    header_file = tmp_path / "simple_data.h"
    header_file.write_text(c_code)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    generate_cbor_code(header_file, output_dir, cpp_path=cpp_info['cpp_path'], cpp_args=cpp_info['cpp_args'])

    assert (output_dir / "cbor_generated.h").exists()
    assert (output_dir / "cbor_generated.c").exists()
    assert (output_dir / "CMakeLists.txt").exists()

    # Basic check for content (can be more thorough)
    generated_c_content = (output_dir / "cbor_generated.c").read_text()
    assert "encode_SimpleData" in generated_c_content
    assert "decode_SimpleData" in generated_c_content
    assert "id" in generated_c_content
    assert "name" in generated_c_content
    assert "is_active" in generated_c_content

    generated_h_content = (output_dir / "cbor_generated.h").read_text()
    assert "encode_SimpleData" in generated_h_content
    assert "decode_SimpleData" in generated_h_content

    cmake_content = (output_dir / "CMakeLists.txt").read_text()
    assert "add_library(cbor_generated STATIC cbor_generated.c)" in cmake_content
    # Updated assertion to match the new CMake template logic
    assert "target_link_libraries(cbor_generated PRIVATE ${TINYCBOR_LIBRARY})" in cmake_content
