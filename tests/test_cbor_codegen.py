import pytest
from pycparser import c_parser, c_ast

# Corrected imports:
# - collect_struct_definitions was removed
# - generate_cbor_code was renamed to generate_cbor_code_for_struct
from cbor_codegen import (
    parse_c_string,
    generate_cbor_code_for_struct,
    StructDefinition,
    StructMember,
    find_struct,
    find_typedef,
    extract_base_type_info,
    expand_in_place
)

# --- Test StructMember and StructDefinition dataclasses ---
def test_struct_member_dataclass():
    member = StructMember(name="id", type_name="int", type_category="primitive")
    assert member.name == "id"
    assert member.type_name == "int"
    assert member.type_category == "primitive"
    assert member.array_size is None

    member_array = StructMember(name="data", type_name="uint8_t", type_category="array", array_size=10)
    assert member_array.array_size == 10
    assert member_array.type_category == "array"

    # Test immutability (frozen=True)
    with pytest.raises(AttributeError):
        member.name = "new_id"

def test_struct_definition_dataclass():
    member1 = StructMember(name="id", type_name="int", type_category="primitive")
    member2 = StructMember(name="name", type_name="char", type_category="char_array", array_size=32)
    
    struct_def = StructDefinition(name="MyStruct", members=[member1, member2])
    assert struct_def.name == "MyStruct"
    assert len(struct_def.members) == 2
    assert struct_def.members[0].name == "id"
    assert struct_def.members[1].name == "name"

    # Test default_factory for members
    empty_struct = StructDefinition(name="EmptyStruct")
    assert empty_struct.name == "EmptyStruct"
    assert empty_struct.members == []

    # Ensure members list is mutable for StructDefinition (not frozen)
    empty_struct.members.append(member1)
    assert len(empty_struct.members) == 1

# --- Test parse_c_string ---
def test_parse_c_string_simple():
    c_code = "struct MyStruct { int a; float b; };"
    ast = parse_c_string(c_code)
    assert isinstance(ast, c_ast.FileAST)
    assert len(ast.ext) > 0

def test_parse_c_string_with_typedef():
    c_code = "typedef unsigned int uint32_t; struct MyStruct { uint32_t id; };"
    ast = parse_c_string(c_code)
    assert isinstance(ast, c_ast.FileAST)

def test_parse_c_string_error_handling():
    invalid_c_code = "struct MyStruct { int a float b; };" # Missing semicolon
    with pytest.raises(c_parser.ParseError):
        parse_c_string(invalid_c_code)

# --- Test find_struct ---
def test_find_struct_by_name():
    c_code = """
    struct MyStruct { int a; };
    typedef struct AnotherStruct { float b; } AnotherStruct_t;
    """
    ast = parse_c_string(c_code)
    
    my_struct = find_struct("MyStruct", ast)
    assert my_struct is not None
    assert my_struct.name == "MyStruct"

    another_struct = find_struct("AnotherStruct", ast)
    assert another_struct is not None
    assert another_struct.name == "AnotherStruct"

    # Test finding by typedef name (should return the underlying struct)
    another_struct_typedef = find_struct("AnotherStruct_t", ast)
    assert another_struct_typedef is not None
    assert another_struct_typedef.name == "AnotherStruct"

    assert find_struct("NonExistentStruct", ast) is None

# --- Test find_typedef ---
def test_find_typedef_by_name():
    c_code = """
    typedef unsigned int uint32_t;
    typedef struct MyStruct { int a; } MyStruct_t;
    """
    ast = parse_c_string(c_code)

    uint32_t_def = find_typedef("uint32_t", ast)
    assert uint32_t_def is not None
    assert isinstance(uint32_t_def, c_ast.IdentifierType)
    assert 'unsigned' in uint32_t_def.names and 'int' in uint32_t_def.names

    my_struct_t_def = find_typedef("MyStruct_t", ast)
    assert my_struct_t_def is not None
    assert isinstance(my_struct_t_def, c_ast.TypeDecl)
    assert isinstance(my_struct_t_def.type, c_ast.Struct)
    assert my_struct_t_def.type.name == "MyStruct"

    assert find_typedef("NonExistentTypedef", ast) is None

# --- Test extract_base_type_info ---
def test_extract_base_type_info_primitives():
    c_code = "int a; unsigned long b; float c; _Bool d;"
    ast = parse_c_string(c_code)
    
    # Helper to get type node from a simple declaration
    def get_type_node(decl_name, ast_node):
        for node in ast_node.ext:
            if isinstance(node, c_ast.Decl) and node.name == decl_name:
                return node.type
        return None

    info = extract_base_type_info(get_type_node("a", ast), ast)
    assert info == {'type_name': 'int', 'type_category': 'primitive', 'array_size': None}

    info = extract_base_type_info(get_type_node("b", ast), ast)
    assert info == {'type_name': 'unsigned long', 'type_category': 'primitive', 'array_size': None}

    info = extract_base_type_info(get_type_node("c", ast), ast)
    assert info == {'type_name': 'float', 'type_category': 'primitive', 'array_size': None}

    info = extract_base_type_info(get_type_node("d", ast), ast)
    assert info == {'type_name': '_Bool', 'type_category': 'primitive', 'array_size': None}

def test_extract_base_type_info_arrays():
    c_code = "char name[32]; int values[10];"
    ast = parse_c_string(c_code)

    def get_type_node(decl_name, ast_node):
        for node in ast_node.ext:
            if isinstance(node, c_ast.Decl) and node.name == decl_name:
                return node.type
        return None

    info = extract_base_type_info(get_type_node("name", ast), ast)
    assert info == {'type_name': 'char', 'type_category': 'char_array', 'array_size': 32}

    info = extract_base_type_info(get_type_node("values", ast), ast)
    assert info == {'type_name': 'int', 'type_category': 'array', 'array_size': 10}

def test_extract_base_type_info_pointers():
    c_code = "char* ptr_char; int* ptr_int;"
    ast = parse_c_string(c_code)

    def get_type_node(decl_name, ast_node):
        for node in ast_node.ext:
            if isinstance(node, c_ast.Decl) and node.name == decl_name:
                return node.type
        return None

    info = extract_base_type_info(get_type_node("ptr_char", ast), ast)
    assert info == {'type_name': 'char', 'type_category': 'char_ptr', 'array_size': None}

    info = extract_base_type_info(get_type_node("ptr_int", ast), ast)
    assert info == {'type_name': 'int', 'type_category': 'primitive_ptr', 'array_size': None}

def test_extract_base_type_info_structs():
    c_code = """
    struct Inner { int x; };
    struct Outer { struct Inner inner; struct Inner* ptr_inner; };
    """
    ast = parse_c_string(c_code)

    def get_type_node_from_struct_member(struct_name, member_name, ast_node):
        struct_def = find_struct(struct_name, ast_node)
        if struct_def and struct_def.decls:
            for decl in struct_def.decls:
                if isinstance(decl, c_ast.Decl) and decl.name == member_name:
                    return decl.type
        return None

    info = extract_base_type_info(get_type_node_from_struct_member("Outer", "inner", ast), ast)
    assert info == {'type_name': 'Inner', 'type_category': 'struct', 'array_size': None}

    info = extract_base_type_info(get_type_node_from_struct_member("Outer", "ptr_inner", ast), ast)
    assert info == {'type_name': 'Inner', 'type_category': 'struct_ptr', 'array_size': None}

# --- Test expand_in_place ---
def test_expand_in_place_typedef_primitive():
    c_code = """
    typedef int MyInt;
    struct Data { MyInt value; };
    """
    ast = parse_c_string(c_code)
    struct_node = find_struct("Data", ast)
    assert struct_node is not None
    
    # Before expansion, the type of 'value' should be IdentifierType('MyInt')
    member_type_before = struct_node.decls[0].type
    assert isinstance(member_type_before, c_ast.TypeDecl)
    assert isinstance(member_type_before.type, c_ast.IdentifierType)
    assert member_type_before.type.names == ['MyInt']

    expand_in_place(struct_node, ast)

    # After expansion, the type should be IdentifierType('int')
    member_type_after = struct_node.decls[0].type
    assert isinstance(member_type_after, c_ast.TypeDecl)
    assert isinstance(member_type_after.type, c_ast.IdentifierType)
    assert member_type_after.type.names == ['int']

def test_expand_in_place_typedef_struct():
    c_code = """
    struct Inner { int x; };
    typedef struct Inner MyInner_t;
    struct Outer { MyInner_t nested; };
    """
    ast = parse_c_string(c_code)
    struct_node = find_struct("Outer", ast)
    assert struct_node is not None

    # Before expansion, the type of 'nested' should be IdentifierType('MyInner_t')
    member_type_before = struct_node.decls[0].type
    assert isinstance(member_type_before, c_ast.TypeDecl)
    assert isinstance(member_type_before.type, c_ast.IdentifierType)
    assert member_type_before.type.names == ['MyInner_t']

    expand_in_place(struct_node, ast)

    # After expansion, the type should be a Struct('Inner')
    member_type_after = struct_node.decls[0].type
    assert isinstance(member_type_after, c_ast.TypeDecl)
    assert isinstance(member_type_after.type, c_ast.Struct)
    assert member_type_after.type.name == 'Inner'

def test_expand_in_place_nested_typedef_array():
    c_code = """
    typedef char MyChar;
    struct Data { MyChar name[16]; };
    """
    ast = parse_c_string(c_code)
    struct_node = find_struct("Data", ast)
    assert struct_node is not None

    member_type_before = struct_node.decls[0].type
    assert isinstance(member_type_before, c_ast.ArrayDecl)
    assert isinstance(member_type_before.type, c_ast.TypeDecl)
    assert isinstance(member_type_before.type.type, c_ast.IdentifierType)
    assert member_type_before.type.type.names == ['MyChar']

    expand_in_place(struct_node, ast)

    member_type_after = struct_node.decls[0].type
    assert isinstance(member_type_after, c_ast.ArrayDecl)
    assert isinstance(member_type_after.type, c_ast.TypeDecl)
    assert isinstance(member_type_after.type.type, c_ast.IdentifierType)
    assert member_type_after.type.type.names == ['char'] # MyChar should be expanded to char

# --- Test generate_cbor_code_for_struct (basic structure) ---
def test_generate_cbor_code_for_struct_simple():
    c_code = """
    struct SimpleData {
        int32_t id;
        char name[32];
        bool is_active;
    };
    """
    ast = parse_c_string(c_code)
    struct_node = find_struct("SimpleData", ast)
    assert struct_node is not None

    # Ensure expansion happens before generation in real use, or pass an already expanded node
    expand_in_place(struct_node, ast) 

    generated_code = generate_cbor_code_for_struct(struct_node, ast)
    assert generated_code is not None
    assert 'c_implementation' in generated_code
    assert 'encode_prototype' in generated_code
    assert 'decode_prototype' in generated_code

    assert "bool encode_SimpleData(const struct SimpleData* data, CborEncoder* encoder);" in generated_code['encode_prototype']
    assert "bool decode_SimpleData(struct SimpleData* data, CborValue* it);" in generated_code['decode_prototype']
    
    # Check for some expected content in the C implementation
    c_impl = generated_code['c_implementation']
    assert "encode_SimpleData" in c_impl
    assert "decode_SimpleData" in c_impl
    assert 'cbor_encode_int(&map_encoder, data->id);' in c_impl
    assert 'encode_text_string(data->name, &map_encoder)' in c_impl
    assert 'cbor_encode_boolean(&map_encoder, data->is_active)' in c_impl
    assert 'if (strncmp(key, "id", key_len) == 0' in c_impl
    assert 'if (strncmp(key, "name", key_len) == 0' in c_impl
    assert 'if (strncmp(key, "is_active", key_len) == 0' in c_impl

def test_generate_cbor_code_for_struct_nested():
    c_code = """
    struct Inner { int x; };
    struct Outer { struct Inner inner_member; };
    """
    ast = parse_c_string(c_code)
    
    # Need to process Inner first if it's not already in the AST's top level
    # For this test, we'll just get the Outer struct and assume Inner is resolvable
    outer_struct_node = find_struct("Outer", ast)
    assert outer_struct_node is not None
    expand_in_place(outer_struct_node, ast)

    generated_code = generate_cbor_code_for_struct(outer_struct_node, ast)
    assert generated_code is not None
    c_impl = generated_code['c_implementation']
    
    assert "encode_Outer" in c_impl
    assert "decode_Outer" in c_impl
    assert "if (!encode_Inner(&data->inner_member, &map_encoder)) return false;" in c_impl
    assert "if (!decode_Inner(&data->inner_member, &map_it)) return false;" in c_impl

# Add more tests for different types, arrays, pointers, etc.
