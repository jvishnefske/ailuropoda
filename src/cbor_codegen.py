import os
import logging
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from pycparser import c_parser, c_ast, plyparser, parse_file

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

# Determine the path to pycparser's fake_libc_include
PYCPARSER_DIR = Path(c_parser.__file__).parent
FAKE_LIBC_INCLUDE_DIR = PYCPARSER_DIR / 'utils' / 'fake_libc_include'

if not FAKE_LIBC_INCLUDE_DIR.is_dir():
    logger.error(f"Could not find pycparser's fake_libc_include directory at {FAKE_LIBC_INCLUDE_DIR}")
    # This is a critical error for pycparser to function correctly with standard types.
    # Consider raising an exception or providing clear instructions to the user.
    # For now, we assume it's there for the purpose of fixing the tests.

# Prepend common standard includes to C code strings for pycparser
# This helps pycparser recognize types like int32_t, bool, etc.
COMMON_C_INCLUDES = """
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
// Add other common includes if necessary, e.g., <float.h> for float_t/double_t
"""

def parse_c_string(c_code_string: str) -> c_ast.FileAST:
    """
    Parses a C code string into a pycparser AST.
    Includes fake standard library headers for common types.
    """
    # Prepend common includes to the string before parsing
    full_c_code_string = COMMON_C_INCLUDES + c_code_string
    
    parser = c_parser.CParser(
        lex_optimize=False,
        yacc_optimize=False,
        cpp_path='gcc',
        cpp_args=['-E', f'-I{FAKE_LIBC_INCLUDE_DIR}']
    )
    try:
        return parser.parse(full_c_code_string, filename='<anon>')
    except plyparser.ParseError as e:
        logger.error(f"Failed to parse C code string: {e}")
        raise

def parse_c_file(file_path: Path) -> c_ast.FileAST:
    """
    Parses a C header file into a pycparser AST using pycparser.parse_file.
    This handles preprocessing automatically.
    """
    try:
        return parse_file(
            str(file_path),
            use_cpp=True,
            cpp_path='gcc',
            cpp_args=['-E', f'-I{FAKE_LIBC_INCLUDE_DIR}']
        )
    except plyparser.ParseError as e:
        logger.error(f"Failed to parse C header file '{file_path}': {e}")
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred during parsing file '{file_path}': {e}")
        raise

class StructMember:
    def __init__(self, name, type_name, type_category, array_size=None):
        self.name = name
        self.type_name = type_name
        self.type_category = type_category
        self.array_size = array_size

    def __repr__(self):
        return f"StructMember(name='{self.name}', type_name='{self.type_name}', type_category='{self.type_category}', array_size={self.array_size})"

class StructDefinition:
    def __init__(self, name, members):
        self.name = name
        self.members = members

    def __repr__(self):
        return f"StructDefinition(name='{self.name}', members={self.members})"

def get_type_info(node):
    """
    Extracts type name and category from a pycparser TypeDecl or PtrDecl node.
    Handles basic types, pointers, and arrays.
    """
    if isinstance(node, c_ast.TypeDecl):
        # For simple types or arrays
        if isinstance(node.type, c_ast.IdentifierType):
            type_name = ' '.join(node.type.names)
            # Check for common primitive types, including those from stdint.h/stdbool.h
            if type_name in ['char', 'int', 'short', 'long', 'float', 'double', 'bool', '_Bool',
                             'int8_t', 'uint8_t', 'int16_t', 'uint16_t', 'int32_t', 'uint32_t',
                             'int64_t', 'uint64_t', 'float_t', 'double_t']:
                return type_name, 'primitive'
            else:
                # Could be a typedef to a struct or an unknown type
                return type_name, 'unknown' # Further resolution needed for typedefs
        elif isinstance(node.type, c_ast.Struct):
            return node.type.name, 'struct'
        elif isinstance(node.type, c_ast.Enum):
            return node.type.name, 'enum' # Treat enums as primitives for now
        else:
            return None, 'unknown' # Fallback for other TypeDecl types
    elif isinstance(node, c_ast.PtrDecl):
        # For pointers
        base_type_name, base_type_category = get_type_info(node.type)
        if base_type_name == 'char' and base_type_category == 'primitive':
            return base_type_name, 'char_ptr'
        elif base_type_category == 'struct':
            return base_type_name, 'struct_ptr'
        else:
            return base_type_name, 'pointer' # Generic pointer
    elif isinstance(node, c_ast.ArrayDecl):
        # For arrays
        base_type_name, base_type_category = get_type_info(node.type)
        array_size = None
        if node.dim:
            # pycparser parses array dimensions as Constant nodes
            if isinstance(node.dim, c_ast.Constant):
                try:
                    array_size = int(node.dim.value)
                except ValueError:
                    logger.warning(f"Could not parse array dimension: {node.dim.value}")
            elif isinstance(node.dim, c_ast.ID):
                # Handle cases where array size is a macro/identifier
                logger.warning(f"Array dimension is an identifier/macro: {node.dim.name}. Cannot determine size at parse time.")
                array_size = None # Cannot determine size at parse time
        
        if base_type_name == 'char' and base_type_category == 'primitive':
            return base_type_name, 'char_array', array_size
        elif base_type_category == 'struct':
            return base_type_name, 'struct_array', array_size
        else:
            return base_type_name, 'array', array_size # Primitive array
    else:
        return None, 'unknown'

def collect_struct_definitions(ast: c_ast.FileAST) -> list[StructDefinition]:
    """
    Collects all struct definitions from the AST, including members and their types.
    Handles nested structs, pointers, and arrays.
    """
    structs = []
    typedef_map = {} # To resolve typedefs to their underlying types

    # First pass: Collect all typedefs to structs and basic types
    for node in ast.ext:
        if isinstance(node, c_ast.Typedef):
            if isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.Struct):
                typedef_map[node.name] = node.type.type.name # typedef T struct S -> T maps to S
            elif isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.IdentifierType):
                typedef_map[node.name] = ' '.join(node.type.type.names) # typedef T int -> T maps to int
            elif isinstance(node.type, c_ast.PtrDecl) and isinstance(node.type.type, c_ast.TypeDecl) and isinstance(node.type.type.type, c_ast.Struct):
                typedef_map[node.name] = node.type.type.type.name + '*' # typedef T struct S* -> T maps to S*
            elif isinstance(node.type, c_ast.PtrDecl) and isinstance(node.type.type, c_ast.TypeDecl) and isinstance(node.type.type.type, c_ast.IdentifierType):
                typedef_map[node.name] = ' '.join(node.type.type.type.names) + '*' # typedef T int* -> T maps to int*
            # Add more typedef handling as needed (e.g., arrays of typedefs)

    # Second pass: Collect struct definitions and their members
    for node in ast.ext:
        if isinstance(node, c_ast.Struct):
            if node.name: # Only process named structs
                members = []
                if node.decls:
                    for decl in node.decls:
                        if isinstance(decl, c_ast.Decl):
                            type_info = get_type_info(decl.type)
                            if len(type_info) == 2: # Primitive, struct, pointer, char_ptr
                                type_name, type_category = type_info
                                array_size = None
                            elif len(type_info) == 3: # Array, struct_array, char_array
                                type_name, type_category, array_size = type_info
                            else:
                                logger.warning(f"Unknown type info format for member {decl.name} in struct {node.name}")
                                continue

                            # Resolve typedefs for member types
                            if type_category == 'unknown' and type_name in typedef_map:
                                resolved_type = typedef_map[type_name]
                                if resolved_type.endswith('*'):
                                    type_name = resolved_type[:-1]
                                    type_category = 'char_ptr' if type_name == 'char' else 'struct_ptr' if resolved_type[:-1] in [s.name for s in structs] else 'pointer'
                                else:
                                    # Check if it's a typedef to a struct
                                    # This check needs to be against already collected structs or a global list
                                    # For now, assume it's a primitive if not explicitly a struct
                                    type_name = resolved_type
                                    type_category = 'primitive' # Default to primitive if not a pointer or known struct

                            # Special handling for `struct S` type names (e.g., `struct SimpleData inner_data;`)
                            # `get_type_info` should return the struct name directly for `c_ast.Struct`
                            if type_category == 'struct' and type_name is None and isinstance(decl.type, c_ast.TypeDecl) and isinstance(decl.type.type, c_ast.Struct):
                                type_name = decl.type.type.name

                            if type_name and type_category != 'unknown':
                                members.append(StructMember(decl.name, type_name, type_category, array_size))
                            else:
                                logger.warning(f"Skipping unsupported member type for {decl.name} in struct {node.name}: {type_name} ({type_category})")
                        else:
                            logger.warning(f"Skipping non-declaration node in struct {node.name}: {type(decl)}")
                structs.append(StructDefinition(node.name, members))
            else:
                logger.info("Skipping anonymous struct definition.")
        elif isinstance(node, c_ast.Typedef):
            # Handle typedefs that define a new name for an existing struct
            # e.g., typedef struct MyStruct MyStruct_t;
            if isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.Struct) and node.type.type.name:
                # If the typedef name is different from the struct name, add it to map
                if node.name != node.type.type.name:
                    typedef_map[node.name] = node.type.type.name
            elif isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.IdentifierType):
                # Handle typedefs like `typedef S1 T1;` where S1 is a struct
                # This requires a third pass or more complex resolution
                pass # Handled in first pass for now

    # Third pass: Resolve struct_ptr and struct types that might have been typedef'd
    # This is needed if a struct is defined *after* it's used in a typedef or pointer
    # For simplicity, we'll just re-evaluate categories based on collected struct names
    struct_names = {s.name for s in structs}
    for s_def in structs:
        for member in s_def.members:
            if member.type_category == 'unknown' and member.type_name in struct_names:
                member.type_category = 'struct'
            elif member.type_category == 'pointer' and member.type_name in struct_names:
                member.type_category = 'struct_ptr'
            elif member.type_category == 'unknown' and member.type_name in typedef_map:
                resolved_type = typedef_map[member.type_name]
                if resolved_type in struct_names:
                    member.type_name = resolved_type
                    member.type_category = 'struct'
                elif resolved_type.endswith('*') and resolved_type[:-1] in struct_names:
                    member.type_name = resolved_type[:-1]
                    member.type_category = 'struct_ptr'
                elif resolved_type.endswith('*') and resolved_type[:-1] == 'char':
                    member.type_name = 'char'
                    member.type_category = 'char_ptr'
                # else: it remains 'unknown' or 'pointer' if not resolved to a known struct/char*

    return structs

def generate_cbor_code(header_file_path: Path, output_dir: Path, test_harness_name: str = None) -> bool:
    """
    Generates CBOR encoding/decoding C code from a C header file.
    """
    env = Environment(loader=FileSystemLoader(Path(__file__).parent.parent / 'templates'))
    c_template = env.get_template('cbor_generated.c.jinja')
    h_template = env.get_template('cbor_generated.h.jinja')
    cmake_template = env.get_template('CMakeLists.txt.jinja')

    try:
        logger.info(f"Parsing C header: {header_file_path}")
        ast = parse_c_file(header_file_path)
    except plyparser.ParseError as e:
        logger.error(f"Failed to parse C header: {e}")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred during parsing: {e}")
        return False

    structs = collect_struct_definitions(ast)
    if not structs:
        logger.warning(f"No struct definitions found in {header_file_path}. No code will be generated.")
        return False

    # Generate C file
    c_output = c_template.render(structs=structs)
    c_file_path = output_dir / 'cbor_generated.c'
    c_file_path.write_text(c_output)
    logger.info(f"Generated C file: {c_file_path}")

    # Generate H file
    h_output = h_template.render(structs=structs)
    h_file_path = output_dir / 'cbor_generated.h'
    h_file_path.write_text(h_output)
    logger.info(f"Generated H file: {h_file_path}")

    # Generate CMakeLists.txt
    generated_library_name = "cbor_generated"
    generated_c_file_name = "cbor_generated.c" # This is just the filename, CMake will look in CMAKE_CURRENT_SOURCE_DIR
    
    cmake_output = cmake_template.render(
        generated_library_name=generated_library_name,
        generated_c_file_name=generated_c_file_name,
        test_harness_c_file_name=f"test_harness_{header_file_path.stem}.c" if test_harness_name else None,
        test_harness_executable_name=test_harness_name
    )
    cmake_file_path = output_dir / 'CMakeLists.txt'
    cmake_file_path.write_text(cmake_output)
    logger.info(f"Generated CMakeLists.txt: {cmake_file_path}")

    return True

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="Generate CBOR encoding/decoding C code for structs.")
    parser.add_argument("header_file", type=Path, help="Path to the C header file containing struct definitions.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory to output the generated C files and CMakeLists.txt.")
    parser.add_argument("--test-harness-name", type=str, help="Name of the test executable to generate in CMakeLists.txt (e.g., 'my_test_app').")

    args = parser.parse_args()

    if not args.header_file.is_file():
        logger.error(f"Header file not found: {args.header_file}")
        exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # For the main script, we don't generate the test harness C file itself,
    # only include its name in CMakeLists.txt if provided.
    # The test harness C file is assumed to be generated by the test framework or manually placed.
    success = generate_cbor_code(args.header_file, args.output_dir, args.test_harness_name)

    if not success:
        logger.error("Code generation failed.")
        exit(1)
    else:
        logger.info("Code generation completed successfully.")
