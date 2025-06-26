import pytest
from pathlib import Path
import sys
import os

# Add the src directory to the Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from cbor_codegen import parse_c_string, collect_struct_definitions, generate_cbor_code, StructDefinition, StructMember
from pycparser import c_parser # Import c_parser to check AST node types

# Helper to compare lists of StructDefinition objects
def compare_struct_definitions(actual, expected):
    assert len(actual) == len(expected)
    for i in range(len(actual)):
        assert actual[i].name == expected[i].name
        assert len(actual[i].members) == len(expected[i].members)
        for j in range(len(actual[i].members)):
            assert actual[i].members[j].name == expected[i].members[j].name
            assert actual[i].members[j].type_name == expected[i].members[j].type_name
            assert actual[i].members[j].type_category == expected[i].members[j].type_category
            assert actual[i].members[j].array_size == expected[i].members[j].array_size

def test_parse_c_string_simple():
    c_code = """
    struct MyStruct {
        int id;
        char name[32];
    };
    """
    ast = parse_c_string(c_code)
    assert ast is not None
    # You can add more assertions here to check the structure of the AST
    # For example, check if 'MyStruct' is in the AST
    found_struct = False
    for ext in ast.ext:
        if isinstance(ext, c_parser.c_ast.Struct) and ext.name == 'MyStruct':
            found_struct = True
            break
    assert found_struct

def test_parse_c_string_with_typedefs_and_standard_types():
    c_code = """
    typedef unsigned int uint_t;
    struct Data {
        int32_t value;
        bool flag;
        uint_t count;
    };
    """
    ast = parse_c_string(c_code)
    assert ast is not None
    # Check if Data struct is found and its members are correctly parsed
    structs = collect_struct_definitions(ast)
    assert len(structs) == 1
    assert structs[0].name == 'Data'
    assert len(structs[0].members) == 3
    assert structs[0].members[0].name == 'value'
    assert structs[0].members[0].type_name == 'int32_t'
    assert structs[0].members[0].type_category == 'primitive'
    assert structs[0].members[1].name == 'flag'
    assert structs[0].members[1].type_name == 'bool'
    assert structs[0].members[1].type_category == 'primitive'
    assert structs[0].members[2].name == 'count'
    assert structs[0].members[2].type_name == 'unsigned int' # uint_t resolves to unsigned int
    assert structs[0].members[2].type_category == 'primitive'


def test_collect_struct_definitions_no_structs():
    c_code = """
    int main() { return 0; }
    """
    ast = parse_c_string(c_code)
    structs = collect_struct_definitions(ast)
    assert len(structs) == 0

def test_collect_struct_and_typedef_definitions():
    c_code = """
    struct S1 { int a; };
    typedef struct S2 { float b; } T2;
    typedef struct { char c; } T3; // Anonymous struct typedef
    typedef S1 T1; // Typedef to an existing struct tag
    typedef struct S4 { double d; } S4_t; // Typedef with same name as struct tag
    """
    file_ast = parse_c_string(c_code)
    structs = collect_struct_definitions(file_ast)

    expected_structs = [
        StructDefinition('S1', [StructMember('a', 'int', 'primitive')]),
        StructDefinition('S2', [StructMember('b', 'float', 'primitive')]),
        # T3 is an anonymous struct, should be collected with its typedef name if possible,
        # but pycparser typically doesn't give anonymous structs a name unless accessed via typedef.
        # For now, we expect it to be skipped or handled differently.
        # If it's collected, its name might be None or a generated name.
        # Based on current collect_struct_definitions, anonymous structs are skipped.
        StructDefinition('S4', [StructMember('d', 'double', 'primitive')]),
    ]

    # Filter out anonymous structs if they are not named by pycparser
    # The current implementation of collect_struct_definitions skips anonymous structs.
    # So, T3 will not be in the collected list.
    # S1, S2, S4 should be present.
    
    # Sort both lists by name for consistent comparison
    actual_struct_names = sorted([s.name for s in structs])
    expected_struct_names = sorted([s.name for s in expected_structs])
    assert actual_struct_names == expected_struct_names

    # Detailed comparison for each struct
    actual_map = {s.name: s for s in structs}
    expected_map = {s.name: s for s in expected_structs}

    for name in expected_struct_names:
        actual_s = actual_map[name]
        expected_s = expected_map[name]
        assert actual_s.name == expected_s.name
        assert len(actual_s.members) == len(expected_s.members)
        for i in range(len(expected_s.members)):
            assert actual_s.members[i].name == expected_s.members[i].name
            assert actual_s.members[i].type_name == expected_s.members[i].type_name
            assert actual_s.members[i].type_category == expected_s.members[i].type_category
            assert actual_s.members[i].array_size == expected_s.members[i].array_size

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
    structs = collect_struct_definitions(file_ast)

    assert len(structs) == 1
    s = structs[0]
    assert s.name == 'SimpleData'
    assert len(s.members) == 5

    expected_members = [
        StructMember('id', 'int32_t', 'primitive'),
        StructMember('name', 'char', 'char_array', 32),
        StructMember('is_active', 'bool', 'primitive'),
        StructMember('temperature', 'float', 'primitive'),
        StructMember('flags', 'uint8_t', 'array', 4)
    ]
    compare_struct_definitions([s], [StructDefinition('SimpleData', expected_members)])


def test_get_struct_members_nested_and_pointer():
    c_code = """
    struct SimpleData { int id; };
    struct NestedData {
        struct SimpleData inner_data;
        char* description;
        int32_t value;
        struct SimpleData* ptr_data;
    };
    """
    file_ast = parse_c_string(c_code)
    structs = collect_struct_definitions(file_ast)

    # Find SimpleData and NestedData
    simple_data_struct = next((s for s in structs if s.name == 'SimpleData'), None)
    nested_data_struct = next((s for s in structs if s.name == 'NestedData'), None)

    assert simple_data_struct is not None
    assert nested_data_struct is not None

    assert len(simple_data_struct.members) == 1
    assert simple_data_struct.members[0].name == 'id'
    assert simple_data_struct.members[0].type_name == 'int'
    assert simple_data_struct.members[0].type_category == 'primitive'

    assert len(nested_data_struct.members) == 4
    assert nested_data_struct.members[0].name == 'inner_data'
    assert nested_data_struct.members[0].type_name == 'SimpleData'
    assert nested_data_struct.members[0].type_category == 'struct'

    assert nested_data_struct.members[1].name == 'description'
    assert nested_data_struct.members[1].type_name == 'char'
    assert nested_data_struct.members[1].type_category == 'char_ptr'

    assert nested_data_struct.members[2].name == 'value'
    assert nested_data_struct.members[2].type_name == 'int32_t'
    assert nested_data_struct.members[2].type_category == 'primitive'

    assert nested_data_struct.members[3].name == 'ptr_data'
    assert nested_data_struct.members[3].type_name == 'SimpleData'
    assert nested_data_struct.members[3].type_category == 'struct_ptr'


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

    # Check if files were created
    assert (output_dir / "cbor_generated.h").is_file()
    assert (output_dir / "cbor_generated.c").is_file()
    assert (output_dir / "CMakeLists.txt").is_file()

    # Basic check of content (can be more thorough)
    c_content = (output_dir / "cbor_generated.c").read_text()
    h_content = (output_dir / "cbor_generated.h").read_text()

    assert "bool encode_MySimpleStruct" in c_content
    assert "bool decode_MySimpleStruct" in c_content
    assert "cbor_encode_int(&map_encoder, data->id);" in c_content
    assert "encode_text_string(data->name, &map_encoder);" in c_content
    assert "cbor_encode_boolean(&map_encoder, data->active);" in c_content

    assert "struct MySimpleStruct;" in h_content
    assert "bool encode_MySimpleStruct" in h_content
    assert "bool decode_MySimpleStruct" in h_content

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

    # Check if files were created
    assert (output_dir / "cbor_generated.h").is_file()
    assert (output_dir / "cbor_generated.c").is_file()
    assert (output_dir / "CMakeLists.txt").is_file()

    # Basic check of content
    c_content = (output_dir / "cbor_generated.c").read_text()
    h_content = (output_dir / "cbor_generated.h").read_text()

    assert "bool encode_Inner" in c_content
    assert "bool decode_Inner" in c_content
    assert "bool encode_Outer" in c_content
    assert "bool decode_Outer" in c_content

    assert "encode_Inner(&data->inner_field, &map_encoder)" in c_content
    assert "decode_Inner(&data->inner_field, &map_it)" in c_content
    assert "encode_text_string(data->description, &map_encoder)" in c_content
    assert "decode_char_ptr(&data->description, 256, &map_it)" in c_content

    assert "struct Inner;" in h_content
    assert "struct Outer;" in h_content

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

    # Check if files were created
    assert (output_dir / "cbor_generated.h").is_file()
    assert (output_dir / "cbor_generated.c").is_file()
    assert (output_dir / "CMakeLists.txt").is_file()

    # Basic check of content
    c_content = (output_dir / "cbor_generated.c").read_text()
    h_content = (output_dir / "cbor_generated.h").read_text()

    assert "bool encode_EmptyStruct" in c_content
    assert "bool decode_EmptyStruct" in c_content
    assert "cbor_encoder_create_map(encoder, &map_encoder, 0);" in c_content # Empty struct should have 0 members

    assert "struct EmptyStruct;" in h_content

def test_generate_cbor_code_no_structs_in_header(tmp_path):
    header_content = """
    int main() { return 0; }
    """
    header_file = tmp_path / "no_structs.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert not success # Should return False if no structs are found

    # Check that no files were created (or are empty)
    assert not (output_dir / "cbor_generated.h").is_file()
    assert not (output_dir / "cbor_generated.c").is_file()
    assert not (output_dir / "CMakeLists.txt").is_file()

def test_generate_cbor_code_with_struct_array(tmp_path):
    header_content = """
    struct Item {
        int id;
    };
    struct Box {
        struct Item items[3];
    };
    """
    header_file = tmp_path / "struct_array.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success

    c_content = (output_dir / "cbor_generated.c").read_text()
    assert "encode_Item(&data->items[i], &map_encoder)" in c_content
    assert "decode_Item(&data->items[i], &array_it)" in c_content
    assert "cbor_encoder_create_array(&map_encoder, &map_encoder, 3);" in c_content
    assert "cbor_value_get_array_length(&array_it, &array_len);" in c_content
    assert "array_len > 3" in c_content # Check bounds

def test_generate_cbor_code_with_primitive_array(tmp_path):
    header_content = """
    struct Data {
        int values[5];
    };
    """
    header_file = tmp_path / "primitive_array.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success

    c_content = (output_dir / "cbor_generated.c").read_text()
    assert "cbor_encode_int(&map_encoder, data->values[i]);" in c_content
    assert "cbor_encoder_create_array(&map_encoder, &map_encoder, 5);" in c_content
    assert "cbor_value_get_int(&array_it, (int*)&data->values[i]);" in c_content
    assert "array_len > 5" in c_content # Check bounds

def test_generate_cbor_code_with_typedef_struct_member(tmp_path):
    header_content = """
    struct Inner { int x; };
    typedef struct Inner Inner_t;
    struct Outer {
        Inner_t inner_field;
    };
    """
    header_file = tmp_path / "typedef_struct_member.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success

    c_content = (output_dir / "cbor_generated.c").read_text()
    assert "encode_Inner(&data->inner_field, &map_encoder)" in c_content
    assert "decode_Inner(&data->inner_field, &map_it)" in c_content

def test_generate_cbor_code_with_typedef_struct_ptr_member(tmp_path):
    header_content = """
    struct Node { int value; };
    typedef struct Node Node_t;
    struct List {
        Node_t* head;
    };
    """
    header_file = tmp_path / "typedef_struct_ptr_member.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success

    c_content = (output_dir / "cbor_generated.c").read_text()
    assert "encode_Node(data->head, &map_encoder)" in c_content
    assert "decode_Node(data->head, &map_it)" in c_content
    assert "data->head = NULL;" in c_content # Check for NULL handling

def test_generate_cbor_code_with_const_char_ptr(tmp_path):
    header_content = """
    struct Message {
        const char* text;
    };
    """
    header_file = tmp_path / "const_char_ptr.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success

    c_content = (output_dir / "cbor_generated.c").read_text()
    assert "encode_text_string(data->text, &map_encoder)" in c_content
    assert "decode_char_ptr(&data->text, 256, &map_it)" in c_content # Should handle const char* as char* for decoding

def test_generate_cbor_code_with_multiple_structs(tmp_path):
    header_content = """
    struct A { int a_val; };
    struct B { float b_val; };
    struct C { struct A a_field; struct B b_field; };
    """
    header_file = tmp_path / "multiple_structs.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success

    c_content = (output_dir / "cbor_generated.c").read_text()
    h_content = (output_dir / "cbor_generated.h").read_text()

    assert "bool encode_A" in c_content
    assert "bool decode_A" in c_content
    assert "bool encode_B" in c_content
    assert "bool decode_B" in c_content
    assert "bool encode_C" in c_content
    assert "bool decode_C" in c_content

    assert "struct A;" in h_content
    assert "struct B;" in h_content
    assert "struct C;" in h_content

def test_generate_cbor_code_with_uint64_t(tmp_path):
    header_content = """
    struct BigIntData {
        uint64_t large_id;
    };
    """
    header_file = tmp_path / "uint64_t_data.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success

    c_content = (output_dir / "cbor_generated.c").read_text()
    assert "cbor_encode_uint(&map_encoder, data->large_id);" in c_content
    assert "cbor_value_get_uint64(&map_it, (uint64_t*)&data->large_id);" in c_content

def test_generate_cbor_code_with_float_double_t(tmp_path):
    header_content = """
    #include <math.h> // For float_t, double_t
    struct FloatData {
        float_t f_val;
        double_t d_val;
    };
    """
    header_file = tmp_path / "float_data.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success

    c_content = (output_dir / "cbor_generated.c").read_text()
    assert "cbor_encode_float(&map_encoder, data->f_val);" in c_content
    assert "cbor_encode_double(&map_encoder, data->d_val);" in c_content
    assert "cbor_value_get_float(&map_it, &data->f_val);" in c_content
    assert "cbor_value_get_double(&map_it, &data->d_val);" in c_content

def test_generate_cbor_code_with_enum_member(tmp_path):
    header_content = """
    enum Status {
        STATUS_OK,
        STATUS_ERROR
    };
    struct EnumData {
        enum Status current_status;
    };
    """
    header_file = tmp_path / "enum_data.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success

    c_content = (output_dir / "cbor_generated.c").read_text()
    # Enums are treated as primitives (integers)
    assert "cbor_encode_int(&map_encoder, data->current_status);" in c_content
    assert "cbor_value_get_int(&map_it, (int*)&data->current_status);" in c_content

def test_generate_cbor_code_with_nested_typedef_struct(tmp_path):
    header_content = """
    typedef struct InnerStruct {
        int inner_id;
    } InnerStruct_t;

    struct OuterStruct {
        InnerStruct_t nested_instance;
        InnerStruct_t* nested_ptr;
    };
    """
    header_file = tmp_path / "nested_typedef_struct.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success

    c_content = (output_dir / "cbor_generated.c").read_text()
    h_content = (output_dir / "cbor_generated.h").read_text()

    # Check for correct struct names and function calls
    assert "bool encode_InnerStruct" in c_content
    assert "bool decode_InnerStruct" in c_content
    assert "bool encode_OuterStruct" in c_content
    assert "bool decode_OuterStruct" in c_content

    assert "encode_InnerStruct(&data->nested_instance, &map_encoder)" in c_content
    assert "decode_InnerStruct(&data->nested_instance, &map_it)" in c_content
    assert "encode_InnerStruct(data->nested_ptr, &map_encoder)" in c_content
    assert "decode_InnerStruct(data->nested_ptr, &map_it)" in c_content

    assert "struct InnerStruct;" in h_content
    assert "struct OuterStruct;" in h_content

def test_generate_cbor_code_with_typedef_to_primitive_array(tmp_path):
    header_content = """
    typedef int MyIntArray[5];
    struct Data {
        MyIntArray values;
    };
    """
    header_file = tmp_path / "typedef_primitive_array.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success

    c_content = (output_dir / "cbor_generated.c").read_text()
    assert "cbor_encode_int(&map_encoder, data->values[i]);" in c_content
    assert "cbor_encoder_create_array(&map_encoder, &map_encoder, 5);" in c_content
    assert "cbor_value_get_int(&array_it, (int*)&data->values[i]);" in c_content
    assert "array_len > 5" in c_content

def test_generate_cbor_code_with_typedef_to_char_ptr(tmp_path):
    header_content = """
    typedef char* StringPtr;
    struct Document {
        StringPtr title;
    };
    """
    header_file = tmp_path / "typedef_char_ptr.h"
    header_file.write_text(header_content)

    output_dir = tmp_path / "generated"
    output_dir.mkdir()

    success = generate_cbor_code(header_file, output_dir)
    assert success

    c_content = (output_dir / "cbor_generated.c").read_text()
    assert "encode_text_string(data->title, &map_encoder)" in c_content
    assert "decode_char_ptr(&data->title, 256, &map_it)" in c_content

