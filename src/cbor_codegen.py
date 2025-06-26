import argparse
import logging
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from pycparser import c_parser, c_ast

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Helper functions ---

def parse_c_string(c_code_string):
    """
    Parses a C code string into a pycparser AST.
    The string is assumed to be already preprocessed.
    """
    parser = c_parser.CParser()
    # Use parse() for parsing directly from a string.
    # cpp_path and cpp_args are not applicable when parsing a string directly.
    return parser.parse(c_code_string, filename='<anon>')

def _find_struct(struct_name, ast_node):
    """
    Helper to find a struct definition by name in the AST.
    This function should find both `struct MyStruct { ... }` and `typedef struct { ... } MyTypedef;`
    It returns the c_ast.Struct node.
    """
    for ext in ast_node.ext:
        if isinstance(ext, c_ast.Decl) and isinstance(ext.type, c_ast.Struct) and ext.type.name == struct_name:
            return ext.type
        elif isinstance(ext, c_ast.Struct) and ext.name == struct_name:
            return ext
        elif isinstance(ext, c_ast.Typedef) and ext.name == struct_name:
            # Handle typedef struct { ... } MyStruct;
            # or typedef struct TaggedStruct MyStruct;
            # or typedef MyOtherTypedef MyStruct;
            current_type = ext.type
            while isinstance(current_type, (c_ast.TypeDecl, c_ast.PtrDecl)):
                current_type = current_type.type
            if isinstance(current_type, c_ast.Struct):
                return current_type
    return None

def _collect_struct_and_typedef_definitions(ast):
    """
    Collects all struct definitions and typedefs to structs from the AST.
    Returns two dictionaries:
    - struct_defs: {struct_name: c_ast.Struct node}
    - typedef_map: {typedef_name: resolved_c_ast_node}
    """
    struct_defs = {}
    typedef_map = {}

    # First pass: Collect all named struct definitions and direct typedefs to anonymous structs
    for ext in ast.ext:
        if isinstance(ext, c_ast.Decl) and isinstance(ext.type, c_ast.Struct):
            if ext.type.name: # Named struct definition: struct MyStruct { ... };
                struct_defs[ext.type.name] = ext.type
        elif isinstance(ext, c_ast.Struct) and ext.name: # Standalone struct definition: struct MyStruct;
            struct_defs[ext.name] = ext
        elif isinstance(ext, c_ast.Typedef):
            current_type = ext.type
            # Traverse through PtrDecl and TypeDecl to find the base type
            while isinstance(current_type, (c_ast.PtrDecl, c_ast.TypeDecl)):
                current_type = current_type.type

            if isinstance(current_type, c_ast.Struct):
                # typedef struct { ... } MyStruct; or typedef struct TaggedStruct { ... } MyStruct;
                typedef_map[ext.name] = current_type # Map typedef name to the actual Struct node
                if current_type.name: # If the anonymous struct also has a tag
                    struct_defs[current_type.name] = current_type
            elif isinstance(current_type, c_ast.IdentifierType):
                # typedef ExistingType MyNewType;
                typedef_map[ext.name] = current_type

    # Second pass: Resolve typedefs that refer to other typedefs or named structs
    # This is crucial for `typedef S1 T1;` where S1 is a struct.
    for typedef_name, typedef_node in list(typedef_map.items()):
        if isinstance(typedef_node, c_ast.IdentifierType):
            resolved_type = struct_defs.get(typedef_node.names[0])
            if resolved_type:
                typedef_map[typedef_name] = resolved_type
            else:
                # Could be a typedef to a primitive type, or an unresolved struct.
                # For now, we keep it as IdentifierType if not a struct.
                pass
        # If it's a PtrDecl pointing to an IdentifierType, resolve the IdentifierType
        # This handles cases like `typedef struct MyStruct* MyStructPtr;`
        elif isinstance(typedef_node, c_ast.PtrDecl) and isinstance(typedef_node.type, c_ast.TypeDecl) and isinstance(typedef_node.type.type, c_ast.IdentifierType):
            resolved_base_type = struct_defs.get(typedef_node.type.type.names[0])
            if resolved_base_type:
                # Reconstruct the PtrDecl with the resolved struct as its base type
                typedef_map[typedef_name] = c_ast.PtrDecl(type=c_ast.TypeDecl(declname=None, quals=[], type=resolved_base_type))

    return struct_defs, typedef_map

def _get_base_type_and_modifiers(type_node, typedef_map):
    """
    Traverses a type node (e.g., TypeDecl, PtrDecl, ArrayDecl) to find its
    base type (e.g., IdentifierType, Struct) and collects modifiers.
    Returns (base_type_node, is_pointer, array_size).
    """
    is_pointer = False
    array_size = None
    current_node = type_node

    while True:
        if isinstance(current_node, c_ast.PtrDecl):
            is_pointer = True
            current_node = current_node.type
        elif isinstance(current_node, c_ast.ArrayDecl):
            if current_node.dim:
                try:
                    # pycparser's Constant node stores value as string
                    array_size = int(current_node.dim.value)
                except (AttributeError, ValueError):
                    logger.warning(f"Could not determine array size for {current_node.dim}. Assuming dynamic or unknown size.")
                    array_size = None
            current_node = current_node.type
        elif isinstance(current_node, c_ast.TypeDecl):
            current_node = current_node.type
        else:
            break # Reached the base type (IdentifierType, Struct, Union, etc.)

    # Resolve typedefs at the base type level
    if isinstance(current_node, c_ast.IdentifierType):
        typedef_name = ' '.join(current_node.names)
        resolved_typedef = typedef_map.get(typedef_name)
        if resolved_typedef:
            # If the typedef resolves to a pointer, update is_pointer and continue resolving
            if isinstance(resolved_typedef, c_ast.PtrDecl):
                is_pointer = True
                # Recursively get base type from the resolved pointer typedef
                resolved_base, _, _ = _get_base_type_and_modifiers(resolved_typedef.type, typedef_map)
                return resolved_base, is_pointer, array_size
            else:
                current_node = resolved_typedef # Use the resolved node as the new current_node

    return current_node, is_pointer, array_size

def _get_struct_members(struct_node, struct_defs, typedef_map):
    """
    Extracts members from a struct_node, resolving types.
    """
    members = []
    if not struct_node.decls:
        return members # Empty struct

    for decl in struct_node.decls:
        if isinstance(decl, c_ast.Decl):
            member_name = decl.name
            member_type_node = decl.type

            base_type_node, is_pointer, array_size = _get_base_type_and_modifiers(member_type_node, typedef_map)

            type_name = None
            is_struct = False
            member_type_category = 'unknown'

            if isinstance(base_type_node, c_ast.IdentifierType):
                type_name = ' '.join(base_type_node.names)
                # Check if this identifier refers to a known struct
                if type_name in struct_defs:
                    is_struct = True
                    member_type_category = 'struct'
                else:
                    # Assume primitive if not a struct
                    member_type_category = 'primitive'
            elif isinstance(base_type_node, c_ast.Struct):
                type_name = base_type_node.name if base_type_node.name else "anonymous_struct" # Use a placeholder for anonymous
                is_struct = True
                member_type_category = 'struct'
            elif isinstance(base_type_node, c_ast.Union):
                logger.warning(f"Skipping union member '{member_name}' in struct '{struct_node.name}'. Unions are not supported.")
                continue
            elif isinstance(base_type_node, c_ast.FuncDecl):
                logger.warning(f"Skipping function pointer member '{member_name}' in struct '{struct_node.name}'. Function pointers are not supported.")
                continue
            else:
                logger.warning(f"Unsupported base type node for member '{member_name}' in struct '{struct_node.name}': {type(base_type_node).__name__}")
                continue

            # Refine type category based on pointer/array status
            if member_type_category == 'primitive':
                if is_pointer and type_name == 'char':
                    member_type_category = 'char_ptr'
                elif array_size is not None and type_name == 'char':
                    member_type_category = 'char_array'
                elif is_pointer:
                    member_type_category = 'pointer' # Generic pointer to primitive
                elif array_size is not None:
                    member_type_category = 'array' # Array of primitives
            elif member_type_category == 'struct':
                if is_pointer:
                    member_type_category = 'struct_ptr' # Pointer to struct
                elif array_size is not None:
                    member_type_category = 'struct_array' # Array of structs

            members.append({
                'name': member_name,
                'type_name': type_name,
                'is_pointer': is_pointer,
                'array_size': array_size,
                'is_struct': is_struct,
                'type_category': member_type_category
            })
    return members

def generate_cbor_code(header_file_path, output_dir):
    """
    Generates CBOR encoding/decoding C code for structs in the given header file.
    """
    logger.info(f"Parsing C header: {header_file_path}")

    with open(header_file_path, 'r') as f:
        c_code_string = f.read()

    # pycparser needs some dummy defines for standard types if not using a full C preprocessor
    # For simplicity, we'll add common ones. For real projects, consider preprocessing
    # the header file externally (e.g., using gcc -E) before passing it to this script.
    fake_libc_includes = """
    #define __attribute__(x)
    #define __extension__
    #define __restrict
    #define __inline__
    #define __asm__(x)
    typedef unsigned long size_t;
    typedef unsigned char uint8_t;
    typedef unsigned short uint16_t;
    typedef unsigned int uint32_t;
    typedef unsigned long long uint64_t;
    typedef signed char int8_t;
    typedef signed short int16_t;
    typedef signed int int32_t;
    typedef signed long long int64_t;
    typedef float float_t;
    typedef double double_t;
    typedef int _Bool;
    #define bool _Bool
    #define true 1
    #define false 0
    """
    c_code_string = fake_libc_includes + c_code_string

    try:
        file_ast = parse_c_string(c_code_string)
    except c_parser.ParseError as e:
        logger.error(f"Failed to parse C header: {e}")
        return False

    struct_definitions = []
    struct_defs_map, typedef_map = _collect_struct_and_typedef_definitions(file_ast)

    # Process structs in a defined order (e.g., topological sort) to ensure nested structs are defined first
    # For simplicity, we'll just iterate through the collected struct_defs_map.
    # A more robust solution would involve a topological sort to handle dependencies.
    # For now, assume simple_data.h has structs defined in a reasonable order.
    for struct_name in sorted(struct_defs_map.keys()): # Sort for consistent output
        struct_node = struct_defs_map[struct_name]
        members = _get_struct_members(struct_node, struct_defs_map, typedef_map)
        struct_definitions.append({
            'name': struct_name,
            'members': members
        })

    # Setup Jinja2 environment
    templates_dir = Path(__file__).parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(templates_dir))

    # Render header file
    header_template = env.get_template("cbor_generated.h.jinja")
    rendered_header = header_template.render(structs=struct_definitions)
    (output_dir / "cbor_generated.h").write_text(rendered_header)
    logger.info(f"Generated cbor_generated.h in {output_dir}")

    # Render C file
    c_template = env.get_template("cbor_generated.c.jinja")
    rendered_c = c_template.render(structs=struct_definitions)
    (output_dir / "cbor_generated.c").write_text(rendered_c)
    logger.info(f"Generated cbor_generated.c in {output_dir}")

    return True

def main():
    parser = argparse.ArgumentParser(description="Generate CBOR encoding/decoding C code for structs.")
    parser.add_argument("header_file", type=Path, help="Path to the C header file containing struct definitions.")
    parser.add_argument("--output-dir", type=Path, default=Path("./generated_cbor"),
                        help="Directory to output the generated C files.")
    # Removed --cpp-path and --cpp-args as they are not used when parsing a string directly.
    # Users should preprocess their header files externally if complex preprocessing is needed.

    parsed_args = parser.parse_args()

    if not parsed_args.header_file.exists():
        logger.error(f"Header file not found: {parsed_args.header_file}")
        exit(1)

    parsed_args.output_dir.mkdir(parents=True, exist_ok=True)

    generate_cbor_code(parsed_args.header_file, parsed_args.output_dir)

if __name__ == "__main__":
    main()
