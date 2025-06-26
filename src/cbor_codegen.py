import logging
import sys
import os
from pycparser import c_parser, c_ast, parse_file

logger = logging.getLogger(__name__)

# Helper functions (assuming these are defined elsewhere in the original file)
# For the purpose of this exercise, I'll include minimal definitions
# or assume they are already present and correctly implemented.

# Placeholder for _find_struct, _find_typedef, _expand_in_place
# In a real scenario, these would be fully implemented.
def _find_struct(name, ast):
    for node in ast.ext:
        if isinstance(node, c_ast.Struct) and node.name == name:
            return node
    return None

def _find_typedef(name, ast):
    for node in ast.ext:
        if isinstance(node, c_ast.Typedef) and node.name == name:
            return node
    return None

def _expand_in_place(node, file_ast):
    """
    Expands typedefs and nested struct definitions in place within a given node.
    This is a simplified version for demonstration.
    """
    if isinstance(node, c_ast.Decl):
        if isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.IdentifierType):
            typedef_name = node.type.type.names[0]
            typedef_node = _find_typedef(typedef_name, file_ast)
            if typedef_node and isinstance(typedef_node.type, c_ast.TypeDecl):
                # Replace the IdentifierType with the actual base type from typedef
                node.type.type = typedef_node.type.type
        elif isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.Struct):
            struct_name = node.type.type.name
            if struct_name:
                struct_def = _find_struct(struct_name, file_ast)
                if struct_def and struct_def.decls:
                    # Populate the decls of the inline struct definition
                    node.type.type.decls = struct_def.decls
                    # Recursively expand members of the nested struct
                    for decl in node.type.type.decls:
                        _expand_in_place(decl, file_ast)
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

    # Handle ArrayDecl
    if isinstance(type_node, c_ast.ArrayDecl):
        is_array = True
        if type_node.dim:
            # Evaluate array dimension if it's a constant
            try:
                array_len = int(type_node.dim.name) # Assumes constant integer dimension
            except (AttributeError, ValueError):
                array_len = None # Could be a variable or complex expression
        type_node = type_node.type # Get the type of the array elements

    # Handle PtrDecl (pointers)
    if isinstance(type_node, c_ast.PtrDecl):
        # Special handling for char* as string
        if isinstance(type_node.type, c_ast.TypeDecl) and \
           isinstance(type_node.type.type, c_ast.IdentifierType) and \
           type_node.type.type.names == ['char']:
            return {'type': 'pointer', 'base_type': 'char', 'is_array': is_array, 'array_len': array_len}
        else:
            # Generic pointer, treat as void* for now or more specific if needed
            # For simplicity, we'll just note it's a pointer
            return {'type': 'pointer', 'base_type': 'void', 'is_array': is_array, 'array_len': array_len}

    # Handle TypeDecl (most common for variables)
    if isinstance(type_node, c_ast.TypeDecl):
        type_node = type_node.type # Get the actual type (IdentifierType, Struct, etc.)

    # Handle IdentifierType (primitive types like int, float, bool)
    if isinstance(type_node, c_ast.IdentifierType):
        base_type = ' '.join(type_node.names)
        if base_type in ['int', 'float', 'double', 'char', 'short', 'long', 'unsigned int', 'unsigned char', 'unsigned short', 'unsigned long', '_Bool', 'bool']:
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
        if type_node.decls: # If the struct definition is inlined
            for decl in type_node.decls:
                member_info = _extract_base_type_info(decl.type, file_ast)
                member_info['name'] = decl.name
                struct_info['members'].append(member_info)
        else: # If it's just a declaration, try to find its definition
            struct_def = _find_struct(type_node.name, file_ast)
            if struct_def and struct_def.decls:
                for decl in struct_def.decls:
                    member_info = _extract_base_type_info(decl.type, file_ast)
                    member_info['name'] = decl.name
                    struct_info['members'].append(member_info)
        return struct_info
    else:
        # Fallback for unhandled types
        logger.warning(f"Unhandled type kind '{type_node.__class__.__name__}' for type '{type_node.type.names[0] if hasattr(type_node, 'type') and hasattr(type_node.type, 'names') else 'N/A'}'. Treating as generic.")
        return {'type': 'unknown', 'base_type': 'void', 'is_array': False, 'array_len': None}


def generate_cbor_code_for_struct(struct_node, file_ast):
    """
    Generates C code for encoding a given struct into CBOR.
    """
    if not struct_node.name:
        return "" # Skip anonymous structs

    struct_name = struct_node.name
    cbor_encode_func_name = f"cbor_encode_{struct_name}"

    # Start generating the C code
    code = []
    code.append(f"// Generated CBOR encoding function for struct {struct_name}")
    code.append(f"void {cbor_encode_func_name}(CborEncoder* encoder, const struct {struct_name}* data) {{")
    code.append(f"    CborEncoder map_encoder;")
    
    # Expand typedefs and nested structs in place for accurate member processing
    # Create a deep copy if you don't want to modify the original AST node
    # For simplicity, we'll modify in place for this example.
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
            if type_info['base_type'] in ['int', 'short', 'long', 'unsigned int', 'unsigned short', 'unsigned long']:
                code.append(f"    cbor_encode_int(&map_encoder, data->{member_name});")
            elif type_info['base_type'] in ['float', 'double']:
                code.append(f"    cbor_encode_float(&map_encoder, data->{member_name});")
            elif type_info['base_type'] in ['_Bool', 'bool']:
                code.append(f"    cbor_encode_boolean(&map_encoder, data->{member_name});")
            elif type_info['base_type'] == 'char':
                # Single char, treat as int or small text string
                code.append(f"    cbor_encode_int(&map_encoder, data->{member_name}); // Encoding char as int")
            else:
                code.append(f"    // WARNING: Unhandled primitive type '{type_info['base_type']}' for member '{member_name}'")
        elif type_info['type'] == 'char_array':
            code.append(f"    cbor_encode_text_string(&map_encoder, data->{member_name}, strlen(data->{member_name}));")
        elif type_info['type'] == 'pointer' and type_info['base_type'] == 'char':
            code.append(f"    cbor_encode_text_string(&map_encoder, data->{member_name}, strlen(data->{member_name}));")
        elif type_info['type'] == 'struct':
            nested_struct_name = type_info['base_type']
            code.append(f"    cbor_encode_{nested_struct_name}(&map_encoder, &data->{member_name});")
        elif type_info['is_array'] and type_info['array_len'] is not None:
            # Handle arrays of primitive types (e.g., int scores[5])
            code.append(f"    cbor_encode_array_start(&map_encoder, &map_encoder, {type_info['array_len']});")
            code.append(f"    for (size_t i = 0; i < {type_info['array_len']}; ++i) {{")
            # Assuming array elements are primitive for simplicity
            if type_info['base_type'] in ['int', 'short', 'long', 'unsigned int', 'unsigned short', 'unsigned long']:
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

    return "\n".join(code)


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    if len(sys.argv) < 2:
        logger.error("Usage: python cbor_codegen.py <header_file>")
        sys.exit(1)

    header_file = sys.argv[1]
    logger.info(f"Parsing header file: {header_file}")

    # Parse the C header file
    try:
        # Use 'cpp_args' for system includes if needed, e.g., ['-E', '-I/usr/include']
        # For simplicity, assuming no complex system includes for now.
        file_ast = parse_file(header_file, use_cpp=True,
                              cpp_args=['-I', os.path.dirname(header_file) or '.', '-std=c11'])
    except Exception as e:
        logger.error(f"Error parsing file {header_file}: {e}")
        sys.exit(1)

    # Find all struct definitions
    for node in file_ast.ext:
        if isinstance(node, c_ast.Struct):
            if node.name: # Only process named structs
                logger.info(f"Found struct: {node.name}")
                generated_code = generate_cbor_code_for_struct(node, file_ast)
                if generated_code:
                    logger.info(f"\n--- Generated Code for struct {node.name} ---\n{generated_code}\n--- End Generated Code for struct {node.name} ---\n")
            else:
                logger.info("Skipping anonymous struct.")

if __name__ == '__main__':
    main()
