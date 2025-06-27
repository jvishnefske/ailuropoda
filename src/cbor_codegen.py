import os
import logging
import argparse
from dataclasses import dataclass, field
from jinja2 import Environment, FileSystemLoader
from pycparser import c_parser, c_ast, parse_file
from typing import Optional, List

logger = logging.getLogger(__name__)

# Configure Jinja2 environment to load templates from the 'templates' directory
# Assuming templates are in a 'templates' directory relative to this script
script_dir = os.path.dirname(__file__)
templates_dir = os.path.join(script_dir, '..', 'templates')
env = Environment(loader=FileSystemLoader(templates_dir),
                  trim_blocks=True,
                  lstrip_blocks=True)

def parse_c_string(c_code_string, cpp_path='gcc', cpp_args=None):
    """
    Parses a C code string into a pycparser AST.
    Args:
        c_code_string (str): The C code as a string.
        cpp_path (str): Path to the C preprocessor (e.g., 'clang', 'gcc').
        cpp_args (list): List of arguments to pass to the C preprocessor.
    Returns:
        c_ast.FileAST: The parsed AST.
    """
    if cpp_args is None:
        cpp_args = ['-E']
    try:
        # Use parse_file with a dummy filename and then pass the string
        # This allows pycparser to correctly handle #line directives if present
        # For simple string parsing, a direct parser.parse() is also an option
        parser = c_parser.CParser()
        return parser.parse(c_code_string, filename='<string>')
    except c_parser.ParseError as e:
        logger.error(f"Error parsing C code: {e}")
        raise

@dataclass(frozen=True) # frozen=True makes instances immutable and hashable
class StructMember:
    name: str
    type_name: str
    type_category: str
    array_size: Optional[int] = None

@dataclass
class StructDefinition:
    name: str
    members: List[StructMember] = field(default_factory=list)

# These functions are made public for testing and potential external use
def find_struct(name, ast):
    """
    Finds a struct definition by name in the AST.
    """
    for node in ast.ext:
        if isinstance(node, c_ast.Decl) and isinstance(node.type, c_ast.Struct) and node.type.name == name:
            return node.type
        elif isinstance(node, c_ast.Typedef) and isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.Struct) and node.name == name:
            return node.type.type
    return None

def find_typedef(name, ast):
    """
    Finds a typedef definition by name in the AST.
    """
    for node in ast.ext:
        if isinstance(node, c_ast.Typedef) and node.name == name:
            return node.type
    return None

def extract_base_type_info(type_node, ast):
    """
    Extracts base type name, category, and array size from a pycparser type node.
    Handles typedefs and pointers.
    """
    type_name = None
    type_category = 'unknown'
    array_size = None

    if isinstance(type_node, c_ast.TypeDecl):
        # Base type (e.g., int, char[32], struct MyStruct)
        if isinstance(type_node.type, c_ast.IdentifierType):
            type_name = ' '.join(type_node.type.names)
            type_category = 'primitive'
            # Check for bool specifically
            if type_name in ['_Bool', 'bool']:
                type_category = 'primitive'
        elif isinstance(type_node.type, c_ast.Struct):
            type_name = type_node.type.name
            type_category = 'struct'
        elif isinstance(type_node.type, c_ast.ArrayDecl):
            # This case should be handled by the outer ArrayDecl
            pass # Will be handled by the ArrayDecl branch below
        elif isinstance(type_node.type, c_ast.PtrDecl):
            # This case should be handled by the outer PtrDecl
            pass # Will be handled by the PtrDecl branch below
        else:
            logger.warning(f"Unhandled TypeDecl type: {type(type_node.type)}")
            type_name = str(type_node.type) # Fallback

    elif isinstance(type_node, c_ast.ArrayDecl):
        # Array type (e.g., int arr[10], char str[32])
        if isinstance(type_node.dim, c_ast.Constant):
            try:
                array_size = int(type_node.dim.value)
            except ValueError:
                logger.warning(f"Could not parse array dimension: {type_node.dim.value}")
        
        # Recursively get the base type of the array elements
        base_info = extract_base_type_info(type_node.type, ast) # Use public function
        type_name = base_info['type_name']
        type_category = base_info['type_category']
        
        if type_category == 'char_array': # If it was already a char_array, keep it
            pass
        elif type_name == 'char' and array_size is not None:
            type_category = 'char_array'
        elif type_category == 'struct':
            type_category = 'struct_array'
        else:
            type_category = 'array'

    elif isinstance(type_node, c_ast.PtrDecl):
        # Pointer type (e.g., int*, char*, struct MyStruct*)
        base_info = extract_base_type_info(type_node.type, ast) # Use public function
        type_name = base_info['type_name']
        
        if type_name == 'char':
            type_category = 'char_ptr'
        elif base_info['type_category'] == 'struct':
            type_category = 'struct_ptr'
        else:
            type_category = 'primitive_ptr' # Generic pointer to primitive

    elif isinstance(type_node, c_ast.IdentifierType):
        # This handles cases where a typedef directly refers to a primitive
        type_name = ' '.join(type_node.names)
        type_category = 'primitive'
        if type_name in ['_Bool', 'bool']:
            type_category = 'primitive'

    else:
        logger.warning(f"Unhandled type node: {type(type_node)}")
        type_name = str(type_node) # Fallback

    return {
        'type_name': type_name,
        'type_category': type_category,
        'array_size': array_size
    }

def expand_in_place(struct_node, ast):
    """
    Expands typedefs and nested struct definitions within a struct_node in place.
    """
    if not struct_node.decls:
        return # Nothing to expand if no declarations

    new_decls = []
    for decl in struct_node.decls:
        if isinstance(decl, c_ast.Decl):
            original_type = decl.type
            current_type = original_type

            # Traverse down through PtrDecl and ArrayDecl to find the base TypeDecl or IdentifierType
            while isinstance(current_type, (c_ast.PtrDecl, c_ast.ArrayDecl, c_ast.TypeDecl)):
                if isinstance(current_type, c_ast.TypeDecl) and isinstance(current_type.type, c_ast.IdentifierType):
                    # Check if it's a typedef
                    typedef_name = ' '.join(current_type.type.names)
                    typedef_def = find_typedef(typedef_name, ast) # Use public function
                    if typedef_def:
                        # Replace the IdentifierType with the actual typedef's type
                        if isinstance(current_type.type, c_ast.IdentifierType):
                            current_type.type = typedef_def
                        else:
                            # This case might be more complex, e.g., typedef struct { ... } MyStruct;
                            # For now, assume simple typedefs.
                            pass
                    break # Found base type or typedef, stop
                elif isinstance(current_type, (c_ast.PtrDecl, c_ast.ArrayDecl)):
                    current_type = current_type.type
                else:
                    break # Should not happen, but as a safeguard

            # After resolving typedefs, check for nested structs that might be defined inline
            # or referenced by name.
            # This part is complex and might require a separate AST traversal or a more
            # sophisticated type resolution system. For now, we rely on extract_base_type_info
            # to correctly identify struct types.
            
            new_decls.append(decl)
    struct_node.decls = new_decls


def generate_cbor_code_for_struct(struct_node, ast):
    """
    Generates CBOR encoding/decoding code for a given struct_node.
    """
    struct_name = struct_node.name
    if not struct_name:
        return None # Skip anonymous structs

    members = []
    if struct_node.decls:
        for decl in struct_node.decls:
            if isinstance(decl, c_ast.Decl):
                member_name = decl.name
                type_info = extract_base_type_info(decl.type, ast) # Use public function
                
                # Handle cases where extract_base_type_info might return None for type_name
                if type_info['type_name'] is None:
                    logger.warning(f"Skipping member '{member_name}' in struct '{struct_name}' due to unresolvable type.")
                    continue

                member = StructMember(
                    name=member_name,
                    type_name=type_info['type_name'],
                    type_category=type_info['type_category'],
                    array_size=type_info['array_size']
                )
                members.append(member)
            else:
                logger.warning(f"Skipping non-declaration node in struct {struct_name}: {type(decl)}")

    struct_def = StructDefinition(name=struct_name, members=members)

    # Render C implementation
    c_template = env.get_template('cbor_generated.c.jinja')
    c_implementation = c_template.render(structs=[struct_def])

    # Render H prototypes (simplified for this example, actual template might be different)
    h_template = env.get_template('cbor_generated.h.jinja')
    h_prototypes = h_template.render(structs=[struct_def])

    return {
        'c_implementation': c_implementation,
        'encode_prototype': f"bool encode_{struct_name}(const struct {struct_name}* data, CborEncoder* encoder);",
        'decode_prototype': f"bool decode_{struct_name}(struct {struct_name}* data, CborValue* it);"
    }


def main():
    parser = argparse.ArgumentParser(description="Generate CBOR encoding/decoding functions for C structs.")
    parser.add_argument("input_header", help="Path to the C header file containing struct definitions.")
    parser.add_argument("--output-dir", required=True, help="Directory to output the generated C, H, and CMake files.")
    parser.add_argument("--cpp-path", default="gcc", help="Path to the C preprocessor (e.g., 'clang', 'gcc').")
    parser.add_argument("--cpp-args", nargs='*', default=['-E'],
                        help="Arguments to pass to the C preprocessor (e.g., '-I/path/to/includes').")
    args = parser.parse_args()

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    # Read the input header file
    with open(args.input_header, 'r') as f:
        c_code_string = f.read()

    # Parse the C code into an AST
    logger.info(f"Parsing C header: {args.input_header}")
    file_ast = parse_c_string(c_code_string, cpp_path=args.cpp_path, cpp_args=args.cpp_args)

    # Collect generated code for all structs
    all_struct_defs = [] # Use StructDefinition objects directly for rendering

    # Find all struct definitions and generate code
    for node in file_ast.ext:
        if isinstance(node, c_ast.Decl) and isinstance(node.type, c_ast.Struct):
            struct_node = node.type
            if struct_node.name: # Only process named structs
                logger.info(f"Processing struct: {struct_node.name}")
                
                # Ensure struct is fully expanded before generating code
                # This modifies struct_node in place by resolving typedefs and nested structs
                expand_in_place(struct_node, file_ast) # Use public function

                # Extract members and create StructDefinition
                members = []
                if struct_node.decls:
                    for decl in struct_node.decls:
                        if isinstance(decl, c_ast.Decl):
                            member_name = decl.name
                            type_info = extract_base_type_info(decl.type, file_ast) # Use public function
                            if type_info['type_name'] is None:
                                logger.warning(f"Skipping member '{member_name}' in struct '{struct_node.name}' due to unresolvable type.")
                                continue
                            member = StructMember(
                                name=member_name,
                                type_name=type_info['type_name'],
                                type_category=type_info['type_category'],
                                array_size=type_info['array_size']
                            )
                            members.append(member)
                        else:
                            logger.warning(f"Skipping non-declaration node in struct {struct_node.name}: {type(decl)}")
                
                all_struct_defs.append(StructDefinition(name=struct_node.name, members=members))
            else:
                logger.debug(f"Skipping anonymous struct at {node.coord}")

    # Render cbor_generated.h
    h_template = env.get_template('cbor_generated.h.jinja')
    rendered_h = h_template.render(structs=all_struct_defs) # Pass StructDefinition objects
    with open(os.path.join(output_dir, 'cbor_generated.h'), 'w') as f:
        f.write(rendered_h)
    logger.info(f"Generated {os.path.join(output_dir, 'cbor_generated.h')}")

    # Render cbor_generated.c
    c_template = env.get_template('cbor_generated.c.jinja')
    rendered_c = c_template.render(structs=all_struct_defs) # Pass StructDefinition objects
    with open(os.path.join(output_dir, 'cbor_generated.c'), 'w') as f:
        f.write(rendered_c)
    logger.info(f"Generated {os.path.join(output_dir, 'cbor_generated.c')}")

    # Render CMakeLists.txt
    cmake_template = env.get_template('CMakeLists.txt.jinja')
    rendered_cmake = cmake_template.render(
        generated_library_name="cbor_generated",
        generated_c_file_name="cbor_generated.c"
    )
    with open(os.path.join(output_dir, 'CMakeLists.txt'), 'w') as f:
        f.write(rendered_cmake)
    logger.info(f"Generated {os.path.join(output_dir, 'CMakeLists.txt')}")

    logger.info(f"CBOR code generation complete. Output in: {output_dir}")

if __name__ == "__main__":
    main()
