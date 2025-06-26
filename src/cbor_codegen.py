import logging
import sys
import os
from pycparser import c_parser, c_ast, parse_file
import argparse
from pathlib import Path

logger = logging.getLogger(__name__)

def _find_struct(name, ast):
    """
    Finds a struct definition by name in the AST.
    Handles structs defined directly, or wrapped in Decl/Typedef nodes.
    """
    for node in ast.ext:
        struct_node = None
        # Case 1: Direct struct definition (e.g., `struct MyStruct { ... };`)
        if isinstance(node, c_ast.Struct):
            struct_node = node
        # Case 2: Struct definition wrapped in a Decl (common for top-level structs)
        # e.g., `struct MyStruct { int x; };` might be parsed as Decl(type=TypeDecl(type=Struct(name='MyStruct', ...)))
        elif isinstance(node, c_ast.Decl) and \
             isinstance(node.type, c_ast.TypeDecl) and \
             isinstance(node.type.type, c_ast.Struct):
            struct_node = node.type.type
        # Case 3: Struct definition within a Typedef (e.g., `typedef struct MyStruct { ... } MyStructTypedef;`)
        elif isinstance(node, c_ast.Typedef) and \
             isinstance(node.type, c_ast.TypeDecl) and \
             isinstance(node.type.type, c_ast.Struct):
            struct_node = node.type.type
        # Case 4: Struct definition wrapped in a Decl, but TypeDecl is skipped (e.g., Decl(type=Struct(...)))
        elif isinstance(node, c_ast.Decl) and isinstance(node.type, c_ast.Struct):
            struct_node = node.type
        # Case 5: Struct definition within a Typedef, but TypeDecl is skipped (e.g., Typedef(type=Struct(...)))
        elif isinstance(node, c_ast.Typedef) and isinstance(node.type, c_ast.Struct):
            struct_node = node.type

        if struct_node and struct_node.name == name:
            return struct_node
    return None

def _find_typedef(name, ast):
    """
    Finds a typedef definition by name in the AST.
    """
    for node in ast.ext:
        if isinstance(node, c_ast.Typedef) and node.name == name:
            return node
    return None

def _expand_in_place(node, file_ast):
    """
    Expands typedefs and nested struct definitions in place within a given node.
    This function modifies the AST node directly to resolve types.
    """
    if isinstance(node, c_ast.Decl):
        # Handle typedefs
        if isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.IdentifierType):
            typedef_name = node.type.type.names[0]
            typedef_node = _find_typedef(typedef_name, file_ast)
            if typedef_node and isinstance(typedef_node.type, c_ast.TypeDecl):
                # Replace the IdentifierType with the actual base type from typedef
                node.type.type = typedef_node.type.type
            elif typedef_node and isinstance(typedef_node.type, c_ast.Struct): # Handle typedef directly to struct
                node.type.type = typedef_node.type
        # Handle nested struct definitions (anonymous or named inline)
        elif isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.Struct):
            struct_name = node.type.type.name
            if struct_name: # If it's a named struct, find its definition
                struct_def = _find_struct(struct_name, file_ast)
                if struct_def and struct_def.decls:
                    # Populate the decls of the inline struct definition
                    node.type.type.decls = struct_def.decls
                    # Recursively expand members of the nested struct
                    for decl in node.type.type.decls:
                        _expand_in_place(decl, file_ast)
            elif node.type.type.decls: # Anonymous inline struct, expand its members
                for decl in node.type.type.decls:
                    _expand_in_place(decl, file_ast)
        # Handle case where Decl.type is directly Struct (no TypeDecl)
        elif isinstance(node.type, c_ast.Struct):
            struct_name = node.type.name
            if struct_name:
                struct_def = _find_struct(struct_name, file_ast)
                if struct_def and struct_def.decls:
                    node.type.decls = struct_def.decls
                    for decl in node.type.decls:
                        _expand_in_place(decl, file_ast)
            elif node.type.decls: # Anonymous inline struct, expand its members
                for decl in node.type.decls:
                    _expand_in_place(decl, file_ast)

    # If the node itself is a struct (e.g., the top-level struct being processed)
    elif isinstance(node, c_ast.Struct) and node.decls:
        for decl in node.decls:
            _expand_in_place(decl, file_ast)


def _extract_base_type_info(type_node, file_ast):
    """
    Extracts base type information from a pycparser type node.
    Handles primitive types, arrays, pointers, and nested structs.
    """
    is_array = False
    array_len = None

    # Handle ArrayDecl (e.g., int arr[10])
    if isinstance(type_node, c_ast.ArrayDecl):
        is_array = True
        if type_node.dim:
            # Evaluate array dimension if it's a constant
            try:
                if isinstance(type_node.dim, c_ast.Constant):
                    array_len = int(type_node.dim.value)
                elif hasattr(type_node.dim, 'name'): # Fallback for older pycparser or specific cases
                    array_len = int(type_node.dim.name)
                else:
                    array_len = None # Could be a variable or complex expression
            except (AttributeError, ValueError):
                array_len = None
        type_node = type_node.type # Get the type of the array elements

    # Handle PtrDecl (pointers, e.g., char*)
    if isinstance(type_node, c_ast.PtrDecl):
        # Special handling for char* as string
        if isinstance(type_node.type, c_ast.TypeDecl) and \
           isinstance(type_node.type.type, c_ast.IdentifierType) and \
           type_node.type.type.names == ['char']:
            return {'type': 'pointer', 'base_type': 'char', 'is_array': is_array, 'array_len': array_len}
        # Handle case where PtrDecl.type is directly IdentifierType (no TypeDecl)
        elif isinstance(type_node.type, c_ast.IdentifierType) and \
             type_node.type.names == ['char']:
            return {'type': 'pointer', 'base_type': 'char', 'is_array': is_array, 'array_len': array_len}
        else:
            # Generic pointer, recursively extract base type of the pointed-to type
            base_info = _extract_base_type_info(type_node.type, file_ast)
            return {'type': 'pointer', 'base_type': base_info['base_type'], 'is_array': is_array, 'array_len': array_len}

    # Handle TypeDecl (most common for variable declarations, e.g., int x;)
    if isinstance(type_node, c_ast.TypeDecl):
        type_node = type_node.type # Get the actual type (IdentifierType, Struct, etc.)

    # Handle IdentifierType (primitive types like int, float, bool, or typedefs)
    if isinstance(type_node, c_ast.IdentifierType):
        base_type = ' '.join(type_node.names)
        # List of common primitive types, including fixed-width integers
        primitive_types = ['int', 'float', 'double', 'char', 'short', 'long',
                           'unsigned int', 'unsigned char', 'unsigned short', 'unsigned long',
                           '_Bool', 'bool', 'size_t',
                           'int8_t', 'int16_t', 'int32_t', 'int64_t',
                           'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t']
        if base_type in primitive_types:
            return {'type': 'primitive', 'base_type': base_type, 'is_array': is_array, 'array_len': array_len}
        elif base_type == 'char' and is_array:
            return {'type': 'char_array', 'base_type': 'char', 'is_array': is_array, 'array_len': array_len}
        else:
            # Could be a typedef to a struct or another primitive
            typedef_node = _find_typedef(base_type, file_ast)
            if typedef_node:
                # Recursively get info for the typedef's underlying type
                return _extract_base_type_info(typedef_node.type, file_ast)
            else:
                logger.warning(f"Unhandled IdentifierType '{base_type}'. Treating as generic.")
                return {'type': 'unknown', 'base_type': base_type, 'is_array': is_array, 'array_len': array_len}

    # Handle Struct (nested structs)
    if isinstance(type_node, c_ast.Struct):
        struct_info = {'type': 'struct', 'base_type': type_node.name, 'is_array': is_array, 'array_len': array_len, 'members': []}
        if type_node.decls: # If the struct definition is inlined (anonymous or named)
            for decl in type_node.decls:
                member_info = _extract_base_type_info(decl.type, file_ast)
                member_info['name'] = decl.name
                struct_info['members'].append(member_info)
        elif type_node.name: # If it's just a declaration, try to find its definition
            struct_def = _find_struct(type_node.name, file_ast)
            if struct_def and struct_def.decls:
                for decl in struct_def.decls:
                    member_info = _extract_base_type_info(decl.type, file_ast)
                    member_info['name'] = decl.name
                    struct_info['members'].append(member_info)
        return struct_info
    else:
        # Fallback for unhandled types
        type_name = 'N/A'
        if hasattr(type_node, 'type') and hasattr(type_node.type, 'names'):
            type_name = ' '.join(type_node.type.names)
        elif hasattr(type_node, 'name'):
            type_name = type_node.name

        logger.warning(f"Unhandled type kind '{type_node.__class__.__name__}' for type '{type_name}'. Treating as generic.")
        return {'type': 'unknown', 'base_type': 'void', 'is_array': False, 'array_len': None}


def generate_cbor_code_for_struct(struct_node, file_ast):
    """
    Generates C code for encoding a given struct into CBOR.
    Returns a tuple: (generated_code_string, function_prototype_string)
    """
    if not struct_node: # Added check for None struct_node
        return "", ""
    if not struct_node.name:
        return "", "" # Skip anonymous structs

    struct_name = struct_node.name
    cbor_encode_func_name = f"cbor_encode_{struct_name}"
    function_prototype = f"void {cbor_encode_func_name}(CborEncoder* encoder, const struct {struct_name}* data);"

    # Start generating the C code
    code = []
    code.append(f"// Generated CBOR encoding function for struct {struct_name}")
    code.append(f"void {cbor_encode_func_name}(CborEncoder* encoder, const struct {struct_name}* data) {{")
    code.append(f"    CborEncoder map_encoder;")
    
    # Expand typedefs and nested structs in place for accurate member processing
    # Note: This modifies the struct_node passed in. For the current usage (processing each node once), this is fine.
    _expand_in_place(struct_node, file_ast)

    members_to_encode = []
    if struct_node.decls:
        for decl in struct_node.decls:
            if isinstance(decl, c_ast.Decl):
                member_name = decl.name
                type_info = _extract_base_type_info(decl.type, file_ast)
                members_to_encode.append((member_name, type_info))
    
    code.append(f"    cbor_encode_map_start(encoder, &map_encoder, {len(members_to_encode)});")

    if not members_to_encode:
        code.append("    /* No members to encode */")

    for member_name, type_info in members_to_encode:
        code.append(f"    cbor_encode_text_string(&map_encoder, \"{member_name}\", strlen(\"{member_name}\"));")

        if type_info['type'] == 'primitive':
            if type_info['base_type'] in ['int', 'short', 'long', 'unsigned int', 'unsigned short', 'unsigned long',
                                          'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t', 'int8_t', 'int16_t', 'int32_t', 'int64_t', 'size_t']:
                code.append(f"    cbor_encode_int(&map_encoder, data->{member_name});")
            elif type_info['base_type'] in ['float', 'double']:
                code.append(f"    cbor_encode_float(&map_encoder, data->{member_name});")
            elif type_info['base_type'] in ['_Bool', 'bool']:
                code.append(f"    cbor_encode_boolean(&map_encoder, data->{member_name});")
            elif type_info['base_type'] == 'char':
                # Single char, encode as int
                code.append(f"    cbor_encode_int(&map_encoder, data->{member_name}); // Encoding char as int")
            else:
                code.append(f"    // WARNING: Unhandled primitive type '{type_info['base_type']}' for member '{member_name}'")
        elif type_info['type'] == 'char_array':
            code.append(f"    cbor_encode_text_string(&map_encoder, data->{member_name}, strlen(data->{member_name}));")
        elif type_info['type'] == 'pointer' and type_info['base_type'] == 'char':
            # Check for NULL pointer before dereferencing strlen
            code.append(f"    if (data->{member_name}) {{")
            code.append(f"        cbor_encode_text_string(&map_encoder, data->{member_name}, strlen(data->{member_name}));")
            code.append(f"    }} else {{")
            code.append(f"        cbor_encode_null(&map_encoder);")
            code.append(f"    }}")
        elif type_info['type'] == 'struct':
            nested_struct_name = type_info['base_type']
            code.append(f"    cbor_encode_{nested_struct_name}(&map_encoder, &data->{member_name});")
        elif type_info['is_array'] and type_info['array_len'] is not None:
            # Handle arrays of primitive types (e.g., int scores[5])
            code.append(f"    cbor_encode_array_start(&map_encoder, &map_encoder, {type_info['array_len']});")
            code.append(f"    for (size_t i = 0; i < {type_info['array_len']}; ++i) {{")
            # Assuming array elements are primitive for simplicity
            if type_info['base_type'] in ['int', 'short', 'long', 'unsigned int', 'unsigned short', 'unsigned long',
                                          'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t', 'int8_t', 'int16_t', 'int32_t', 'int64_t', 'size_t']:
                code.append(f"        cbor_encode_int(&map_encoder, data->{member_name}[i]);")
            elif type_info['base_type'] in ['float', 'double']:
                code.append(f"        cbor_encode_float(&map_encoder, data->{member_name}[i]);")
            elif type_info['base_type'] in ['_Bool', 'bool']:
                code.append(f"        cbor_encode_boolean(&map_encoder, data->{member_name}[i]);")
            else:
                code.append(f"        // WARNING: Unhandled array element type '{type_info['base_type']}' for member '{member_name}[i]'")
            code.append(f"    }}")
        else:
            code.append(f"    // WARNING: Unhandled type for member '{member_name}'")

    code.append(f"    cbor_encode_map_end(encoder, &map_encoder);")
    code.append(f"}}")
    code.append("") # Add a newline at the end for separation

    return "\n".join(code), function_prototype


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description="Generate CBOR encoding C code for structs from a C header file.")
    parser.add_argument("header_file", help="Path to the C header file containing struct definitions.")
    parser.add_argument("-o", "--output-dir", default="generated_cbor",
                        help="Directory to output generated C source and header files. (default: generated_cbor)")
    args = parser.parse_args()

    header_file_path = Path(args.header_file)
    output_dir_path = Path(args.output_dir)

    if not header_file_path.is_file():
        logger.error(f"Error: Header file not found at '{header_file_path}'")
        sys.exit(1)

    logger.info(f"Parsing header file: {header_file_path}")
    logger.info(f"Output directory: {output_dir_path}")

    # Create output directory if it doesn't exist
    output_dir_path.mkdir(parents=True, exist_ok=True)

    # Parse the C header file
    try:
        # Add the directory of the header file to the include path for pycparser's preprocessor
        cpp_args = ['-I', str(header_file_path.parent) or '.', '-std=c11']
        file_ast = parse_file(str(header_file_path), use_cpp=True, cpp_args=cpp_args)
    except Exception as e:
        logger.error(f"Error parsing file {header_file_path}: {e}")
        sys.exit(1)

    generated_prototypes = []
    
    # Find all struct definitions
    for node in file_ast.ext:
        # Check if the node itself is a struct definition
        if isinstance(node, c_ast.Struct) and node.name:
            logger.info(f"Found struct: {node.name}")
            generated_code, prototype = generate_cbor_code_for_struct(node, file_ast)
            if generated_code:
                # Construct output C file path
                output_c_filename = f"cbor_encode_{node.name}.c"
                output_c_filepath = output_dir_path / output_c_filename

                # Add necessary includes to the generated C file
                c_file_content = []
                c_file_content.append("#include <cbor.h>")
                c_file_content.append(f"#include \"{header_file_path.name}\"") # Include the original header
                c_file_content.append("")
                c_file_content.append(generated_code)

                try:
                    with open(output_c_filepath, "w") as f:
                        f.write("\n".join(c_file_content))
                    logger.info(f"Generated code for struct {node.name} written to {output_c_filepath}")
                    generated_prototypes.append(prototype)
                except IOError as e:
                    logger.error(f"Error writing to file {output_c_filepath}: {e}")
        # Also check if the node is a Decl or Typedef that contains a struct definition
        elif isinstance(node, (c_ast.Decl, c_ast.Typedef)):
            # Check if the type of the declaration/typedef is a struct
            # This part needs to be careful to extract the actual struct node
            struct_node_candidate = None
            if isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.Struct) and node.type.type.name:
                struct_node_candidate = node.type.type
            elif isinstance(node.type, c_ast.Struct) and node.type.name: # Added this case
                struct_node_candidate = node.type

            if struct_node_candidate:
                logger.info(f"Found struct (via Decl/Typedef): {struct_node_candidate.name}")
                generated_code, prototype = generate_cbor_code_for_struct(struct_node_candidate, file_ast)
                if generated_code:
                    output_c_filename = f"cbor_encode_{struct_node_candidate.name}.c"
                    output_c_filepath = output_dir_path / output_c_filename

                    c_file_content = []
                    c_file_content.append("#include <cbor.h>")
                    c_file_content.append(f"#include \"{header_file_path.name}\"")
                    c_file_content.append("")
                    c_file_content.append(generated_code)

                    try:
                        with open(output_c_filepath, "w") as f:
                            f.write("\n".join(c_file_content))
                        logger.info(f"Generated code for struct {struct_node_candidate.name} written to {output_c_filepath}")
                        generated_prototypes.append(prototype)
                    except IOError as e:
                        logger.error(f"Error writing to file {output_c_filepath}: {e}")
            else:
                logger.debug(f"Skipping Decl/Typedef node without a named struct definition: {node.__class__.__name__}")
        else:
            logger.debug(f"Skipping AST node of type: {node.__class__.__name__}")


    # Generate a single header file with all prototypes
    if generated_prototypes:
        output_h_filename = "cbor_generated.h"
        output_h_filepath = output_dir_path / output_h_filename

        h_file_content = []
        h_file_content.append("#ifndef CBOR_GENERATED_H")
        h_file_content.append("#define CBOR_GENERATED_H")
        h_file_content.append("")
        h_file_content.append("#include <cbor.h>") # Include cbor library header
        h_file_content.append(f"#include \"{header_file_path.name}\"") # Include the original header for struct definitions
        h_file_content.append("")
        h_file_content.append("#ifdef __cplusplus")
        h_file_content.append("extern \"C\" {")
        h_file_content.append("#endif")
        h_file_content.append("")
        h_file_content.extend(generated_prototypes)
        h_file_content.append("")
        h_file_content.append("#ifdef __cplusplus")
        h_file_content.append("}")
        h_file_content.append("#endif")
        h_file_content.append("")
        h_file_content.append("#endif // CBOR_GENERATED_H")

        try:
            with open(output_h_filepath, "w") as f:
                f.write("\n".join(h_file_content))
            logger.info(f"Generated header with prototypes written to {output_h_filepath}")
        except IOError as e:
            logger.error(f"Error writing to file {output_h_filepath}: {e}")
    else:
        logger.info("No structs found or no code generated, skipping header file creation.")

if __name__ == '__main__':
    main()
