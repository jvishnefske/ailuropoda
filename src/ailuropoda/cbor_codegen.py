import argparse
import sys
import logging
from pathlib import Path
import tempfile

from pycparser import CParser, c_ast, parse_file
from jinja2 import Environment, FileSystemLoader

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(filename)s:%(lineno)d %(message)s')
logger = logging.getLogger(__name__)

# --- AST Traversal and Helper Functions ---

def find_struct(struct_name, ast):
    """Finds a struct definition by its name in the AST."""
    for ext in ast.ext:
        if isinstance(ext, c_ast.Decl) and isinstance(ext.type, c_ast.Struct):
            if ext.type.name == struct_name:
                return ext.type
        elif isinstance(ext, c_ast.Typedef) and isinstance(ext.type, c_ast.TypeDecl) and isinstance(ext.type.type, c_ast.Struct):
            if ext.type.type.name == struct_name:
                return ext.type.type
    return None

def find_typedef(typedef_name, ast):
    """Finds a typedef definition by its name in the AST."""
    for ext in ast.ext:
        if isinstance(ext, c_ast.Typedef) and ext.name == typedef_name:
            return ext
    return None

def _get_base_type_from_decl(decl_node):
    """
    Helper to get the innermost type node (IdentifierType or Struct)
    from a chain of TypeDecl, PtrDecl, or ArrayDecl nodes.
    """
    current = decl_node
    while isinstance(current, (c_ast.TypeDecl, c_ast.PtrDecl, c_ast.ArrayDecl)):
        current = current.type
    return current

def expand_in_place(node, ast):
    """
    Recursively expands typedefs within a given AST node.
    Modifies the AST in place and returns the modified node.
    """
    if isinstance(node, c_ast.TypeDecl):
        if isinstance(node.type, c_ast.IdentifierType):
            typedef_name = node.type.names[0]
            typedef_node = find_typedef(typedef_name, ast)
            if typedef_node:
                # Get the fully resolved base type from the typedef's definition
                # This handles cases like `typedef int MyInt;` where typedef_node.type is TypeDecl
                # and `typedef struct S MyS;` where typedef_node.type is TypeDecl
                resolved_base_type = _get_base_type_from_decl(typedef_node.type)
                node.type = resolved_base_type # Replace the IdentifierType with the base type
            # If node.type is not an IdentifierType (e.g., it's already a Struct, PtrDecl, ArrayDecl),
            # or if it was an IdentifierType but not a typedef, no further action needed here.
            # The recursive calls below will handle nested structures.
        elif hasattr(node.type, 'type'): # For PtrDecl, ArrayDecl, etc. nested within TypeDecl
            node.type = expand_in_place(node.type, ast)
    elif isinstance(node, c_ast.PtrDecl):
        node.type = expand_in_place(node.type, ast)
    elif isinstance(node, c_ast.ArrayDecl):
        node.type = expand_in_place(node.type, ast)
    elif isinstance(node, c_ast.Struct):
        if node.decls:
            for i, decl in enumerate(node.decls):
                node.decls[i].type = expand_in_place(decl.type, ast)
    # For IdentifierType or Struct nodes directly, no expansion needed, just return
    return node


def get_type_info(node, ast):
    """
    Extracts type information from a C AST node.
    Assumes typedefs have already been expanded by `expand_in_place`.
    Returns a tuple: (base_type_name, type_category, array_size, is_pointer)
    """
    is_pointer = False
    array_size = None
    current_node = node

    # Traverse through PtrDecl and ArrayDecl to find the base type
    while True:
        if isinstance(current_node, c_ast.PtrDecl):
            is_pointer = True
            current_node = current_node.type
        elif isinstance(current_node, c_ast.ArrayDecl):
            if current_node.dim:
                try:
                    array_size = int(current_node.dim.value)
                except (ValueError, TypeError):
                    logger.warning(f"Could not determine array size for {current_node.dim.value}. Assuming dynamic or unknown size.")
                    array_size = None
            current_node = current_node.type
        else:
            break # Reached the base TypeDecl, IdentifierType, or Struct

    # Now current_node should be a TypeDecl, IdentifierType, or Struct
    base_type_name = 'unknown'
    type_category = 'unknown'

    # Mapping for common preprocessed types to their standard C equivalents
    # This helps normalize names like '__uint32_t' to 'unsigned int' or 'uint32_t'
    PREPROCESSED_TYPE_MAP = {
        '__uint8_t': 'unsigned char',
        '__uint16_t': 'unsigned short',
        '__uint32_t': 'unsigned int', # Map to 'unsigned int' to match test expectation
        '__uint64_t': 'unsigned long long',
        '__int8_t': 'signed char',
        '__int16_t': 'short',
        '__int32_t': 'int',
        '__int64_t': 'long long',
        'signed char': 'char',
        'long int': 'long',
        'long long int': 'long long',
        'unsigned long int': 'unsigned long',
        'unsigned long long int': 'unsigned long long',
    }

    if isinstance(current_node, c_ast.TypeDecl):
        # The actual type is inside current_node.type
        if isinstance(current_node.type, c_ast.IdentifierType):
            raw_name = ' '.join(current_node.type.names)
            base_type_name = PREPROCESSED_TYPE_MAP.get(raw_name, raw_name)
        elif isinstance(current_node.type, c_ast.Struct):
            base_type_name = current_node.type.name
        else:
            logger.warning(f"Unexpected type inside TypeDecl: {type(current_node.type)}")
    elif isinstance(current_node, c_ast.Struct):
        base_type_name = current_node.name
    elif isinstance(current_node, c_ast.IdentifierType):
        raw_name = ' '.join(current_node.names)
        base_type_name = PREPROCESSED_TYPE_MAP.get(raw_name, raw_name)
    else:
        logger.warning(f"Unexpected base node type: {type(current_node)}")

    # Determine type category based on base_type_name
    if base_type_name == 'char' and array_size is not None:
        type_category = 'char_array'
    elif base_type_name == 'char' and is_pointer:
        type_category = 'char_ptr'
    elif base_type_name in ['int', 'long', 'short', 'char', 'float', 'double', 'bool', '_Bool', # _Bool for direct bool expansion
                            'int8_t', 'int16_t', 'int32_t', 'int64_t',
                            'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
                            'float_t', 'double_t',
                            'unsigned int', 'unsigned char', 'unsigned short', 'unsigned long', 'unsigned long long',
                            'signed char']: # Include signed char as a primitive
        type_category = 'primitive'
    elif type_category == 'unknown' and base_type_name != 'unknown': # If it's a struct or something else
        if isinstance(current_node, c_ast.Struct) or (isinstance(current_node, c_ast.TypeDecl) and isinstance(current_node.type, c_ast.Struct)):
            type_category = 'struct'
        else:
            type_category = 'unknown_primitive' # Fallback for other primitive-like typedefs

    # Adjust category for arrays and pointers if they were the outermost type
    if array_size is not None:
        if type_category == 'primitive' or type_category == 'unknown_primitive':
            type_category = 'array'
        elif type_category == 'struct':
            type_category = 'struct_array'
    elif is_pointer:
        if type_category == 'struct':
            type_category = 'struct_ptr'
        # char_ptr is already handled

    return base_type_name, type_category, array_size, is_pointer


def parse_c_string(c_code_string, cpp_path=None, cpp_args=None):
    """
    Parses a C code string into a pycparser AST, using a C preprocessor.
    """
    # pycparser's parse_file is the easiest way to leverage cpp.
    # We write the string to a temporary file and then parse it.
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.h', delete=False) as tmp_file:
        tmp_file.write(c_code_string)
        tmp_file_path = tmp_file.name

    try:
        # Ensure cpp_args is a list
        if cpp_args is None:
            cpp_args_list = []
        elif isinstance(cpp_args, str):
            cpp_args_list = [cpp_args]
        else:
            cpp_args_list = cpp_args

        ast = parse_file(
            tmp_file_path,
            use_cpp=True,
            cpp_path=cpp_path,
            cpp_args=cpp_args_list
        )
        return ast
    except Exception as e:
        logger.error(f"Error parsing C code from {tmp_file_path}: {e}")
        raise
    finally:
        Path(tmp_file_path).unlink() # Use pathlib for file removal


def generate_cbor_code(header_file_path, output_dir, cpp_path=None, cpp_args=None):
    """
    Generates CBOR encoding/decoding C code for structs defined in the given header file.
    """
    with open(header_file_path, 'r') as f:
        c_code_string = f.read()

    logger.info(f"Parsing C header: {header_file_path}")
    ast = parse_c_string(c_code_string, cpp_path=cpp_path, cpp_args=cpp_args)

    structs_to_generate = []
    for ext in ast.ext:
        if isinstance(ext, c_ast.Decl) and isinstance(ext.type, c_ast.Struct):
            struct_node = ext.type
            # Only process named structs with declarations
            if struct_node.name and struct_node.decls:
                structs_to_generate.append(struct_node)
        elif isinstance(ext, c_ast.Typedef) and isinstance(ext.type, c_ast.TypeDecl) and isinstance(ext.type.type, c_ast.Struct):
            struct_node = ext.type.type
            # Only process named typedef structs with declarations
            if struct_node.name and struct_node.decls:
                structs_to_generate.append(struct_node)

    processed_structs = []
    for struct_node in structs_to_generate:
        struct_info = {
            'name': struct_node.name,
            'members': []
        }
        if struct_node.decls:
            for decl in struct_node.decls:
                # Expand typedefs for the member's type before processing
                # Assign the returned node back to decl.type
                decl.type = expand_in_place(decl.type, ast)
                base_type_name, type_category, array_size, is_pointer = get_type_info(decl.type, ast)

                member_info = {
                    'name': decl.name,
                    'type_name': base_type_name,
                    'type_category': type_category,
                    'array_size': array_size,
                    'is_pointer': is_pointer
                }
                struct_info['members'].append(member_info)
        processed_structs.append(struct_info)

    # Setup Jinja2 environment
    # Corrected path: go up three levels from cbor_codegen.py to reach project root, then into 'templates'
    templates_dir = Path(__file__).parent.parent.parent / 'templates'
    env = Environment(loader=FileSystemLoader(templates_dir), trim_blocks=True, lstrip_blocks=True)

    # Render C header file
    header_template = env.get_template('cbor_generated.h.jinja')
    # Pass the original header file path relative to the output directory
    # Use pathlib's relative_to with walk_up=True to handle paths outside the output_dir
    relative_original_header_path = header_file_path.relative_to(output_dir, walk_up=True)
    rendered_header = header_template.render(
        structs=processed_structs,
        original_header_path=relative_original_header_path
    )
    (output_dir / 'cbor_generated.h').write_text(rendered_header)
    logger.info(f"Generated {output_dir / 'cbor_generated.h'}")

    # Render C source file
    c_template = env.get_template('cbor_generated.c.jinja')
    rendered_c = c_template.render(structs=processed_structs)
    (output_dir / 'cbor_generated.c').write_text(rendered_c)
    logger.info(f"Generated {output_dir / 'cbor_generated.c'}")

    # Render CMakeLists.txt
    cmake_template = env.get_template('CMakeLists.txt.jinja')
    # For the generated CMakeLists.txt, we don't need test harness info
    # as it's meant to be included by a parent project.
    # The test harness is generated by the test itself.
    rendered_cmake = cmake_template.render(
        generated_library_name="cbor_generated",
        generated_c_file_name="cbor_generated.c",
        test_harness_c_file_name=None, # Not generating test harness here
        test_harness_executable_name=None # Not generating test harness here
    )
    (output_dir / 'CMakeLists.txt').write_text(rendered_cmake)
    logger.info(f"Generated {output_dir / 'CMakeLists.txt'}")


def main():
    parser = argparse.ArgumentParser(description="Generate CBOR encoding/decoding C code for structs.")
    parser.add_argument("header_file", type=Path, help="Path to the C header file containing struct definitions.")
    parser.add_argument("--output-dir", type=Path, default=Path("./generated_cbor"),
                        help="Directory to output the generated C files and CMakeLists.txt.")
    parser.add_argument("--cpp-path", type=str, default='cpp',
                        help="Path to the C preprocessor (cpp) executable. Defaults to 'cpp'.")
    parser.add_argument("--cpp-args", nargs=argparse.REMAINDER, default=[],
                        help="Additional arguments to pass to the C preprocessor (e.g., -I<include_path>).")

    args = parser.parse_args()

    if not args.header_file.is_file():
        logger.error(f"Error: Header file not found at {args.header_file}")
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    try:
        generate_cbor_code(args.header_file, args.output_dir, args.cpp_path, args.cpp_args)
        logger.info("CBOR code generation completed successfully.")
    except Exception as e:
        logger.error(f"CBOR code generation failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
