import sys
import os
import argparse
import logging
import copy
from pycparser import c_parser, c_ast, parse_file
from jinja2 import Environment, FileSystemLoader

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Jinja2 environment setup (assuming templates will be in a 'templates' directory)
script_dir = os.path.dirname(os.path.abspath(__file__))
templates_dir = os.path.join(script_dir, 'templates')
env = Environment(loader=FileSystemLoader(templates_dir), trim_blocks=True, lstrip_blocks=True)

# --- AST Traversal and Manipulation Helpers ---

def parse_c_string(c_code, cpp_path=None, cpp_args=None):
    """
    Parses a C code string into a pycparser AST.
    Optionally uses a C preprocessor.
    """
    parser = c_parser.CParser()
    if cpp_path:
        # Use cpp_path for preprocessing
        # pycparser expects a list of arguments for cpp_args
        if cpp_args is None:
            cpp_args = []
        # Add -E to cpp_args to ensure only preprocessing is done
        if '-E' not in cpp_args:
            cpp_args.insert(0, '-E')
        
        # Create a temporary file for the C code string
        temp_c_file = None
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.c') as f:
                f.write(c_code)
                temp_c_file = f.name
            
            # Parse the preprocessed file
            ast = parse_file(temp_c_file, use_cpp=True, cpp_path=cpp_path, cpp_args=cpp_args)
        finally:
            if temp_c_file and os.path.exists(temp_c_file):
                os.remove(temp_c_file)
    else:
        ast = parser.parse(c_code)
    return ast

def _find_struct(struct_name, ast):
    """
    Finds a struct definition by name in the AST.
    This function should NOT modify the AST.
    """
    for ext in ast.ext:
        if isinstance(ext, c_ast.Decl) and isinstance(ext.type, c_ast.Struct) and ext.type.name == struct_name:
            return ext.type
        elif isinstance(ext, c_ast.Typedef):
            # Check if typedef points to a struct with the given name
            if isinstance(ext.type, c_ast.TypeDecl) and isinstance(ext.type.type, c_ast.Struct):
                # If it's an anonymous struct typedef'd with struct_name, return the struct node.
                # The name will be handled by TypedefResolver when it's used.
                if ext.name == struct_name:
                    return ext.type.type
    return None

class TypedefResolver(c_ast.NodeVisitor):
    """
    A NodeVisitor that resolves typedefs in place.
    It builds a map of typedefs and then replaces Typename nodes with the
    actual type definition.
    """
    def __init__(self, global_ast):
        self.typedef_map = {}
        self.global_ast = global_ast
        self._build_typedef_map()

    def _build_typedef_map(self):
        for node in self.global_ast.ext:
            if isinstance(node, c_ast.Typedef):
                # Store the actual type definition, not the TypeDecl wrapper
                # For `typedef struct { int x; } Point;`, node.type.type is the Struct node.
                # For `typedef int MyInt;`, node.type.type is IdentifierType(['int']).
                self.typedef_map[node.name] = node.type.type

    def visit_Decl(self, node):
        # Handle declarations like 'MyType var;'
        if isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.Typename):
            typedef_name = node.type.type.name
            if typedef_name in self.typedef_map:
                resolved_type = self.typedef_map[typedef_name]
                
                # Create a deep copy to avoid modifying the original shared AST node
                # This is crucial if the same typedef is used multiple times.
                new_type = copy.deepcopy(resolved_type)
                
                # If the resolved type is an anonymous struct, assign the typedef name to it.
                # This handles `typedef struct { ... } MyStruct;`
                if isinstance(new_type, c_ast.Struct) and new_type.name is None:
                    new_type.name = typedef_name
                
                node.type.type = new_type
                # Recursively visit the newly inserted structure's declarations
                self.visit(new_type)
        
        # Handle declarations that are themselves structs (e.g., struct MyStruct { ... };)
        # or pointers to structs (e.g., struct MyStruct* ptr;)
        elif isinstance(node.type, c_ast.PtrDecl) and isinstance(node.type.type, c_ast.TypeDecl) and isinstance(node.type.type.type, c_ast.Typename):
            typedef_name = node.type.type.type.name
            if typedef_name in self.typedef_map:
                resolved_type = self.typedef_map[typedef_name]
                new_type = copy.deepcopy(resolved_type)
                if isinstance(new_type, c_ast.Struct) and new_type.name is None:
                    new_type.name = typedef_name
                node.type.type.type = new_type
                self.visit(new_type)
        
        # Continue visiting children
        self.generic_visit(node)

def _expand_in_place(struct_node, file_ast):
    """
    Expands typedefs within a given struct node using a global AST for typedef definitions.
    Modifies the struct_node in place.
    """
    resolver = TypedefResolver(file_ast)
    resolver.visit(struct_node)


# --- Code Generation Logic (Simplified for this context) ---

def _get_c_type_info(decl):
    """
    Extracts C type information from a pycparser Decl node.
    Returns a dictionary with 'type_name', 'is_pointer', 'array_size', 'is_struct'.
    """
    type_info = {
        'type_name': None,
        'is_pointer': False,
        'array_size': None,
        'is_struct': False,
        'is_const': False,
    }

    current_type = decl.type
    
    # Handle const qualifier
    if hasattr(decl, 'quals') and 'const' in decl.quals:
        type_info['is_const'] = True

    # Traverse through PtrDecl and ArrayDecl
    while True:
        if isinstance(current_type, c_ast.PtrDecl):
            type_info['is_pointer'] = True
            current_type = current_type.type
        elif isinstance(current_type, c_ast.ArrayDecl):
            if current_type.dim:
                # Evaluate array dimension if it's a constant
                try:
                    # pycparser's Constant node stores value as string
                    if isinstance(current_type.dim, c_ast.Constant):
                        type_info['array_size'] = int(current_type.dim.value)
                    elif isinstance(current_type.dim, c_ast.ID):
                        # Handle cases where array size is a macro/enum (not directly evaluable here)
                        # For now, we'll just store the ID name. A real preprocessor would resolve this.
                        type_info['array_size'] = current_type.dim.name
                    else:
                        type_info['array_size'] = None # Cannot determine size
                except (ValueError, TypeError):
                    type_info['array_size'] = None # Cannot parse dimension
            current_type = current_type.type
        elif isinstance(current_type, c_ast.TypeDecl):
            current_type = current_type.type
        else:
            break

    # Get the base type name
    if isinstance(current_type, c_ast.IdentifierType):
        type_info['type_name'] = ' '.join(current_type.names)
    elif isinstance(current_type, c_ast.Struct):
        type_info['is_struct'] = True
        type_info['type_name'] = current_type.name
        if not type_info['type_name']:
            logger.warning(f"Found anonymous struct member '{decl.name}'. This might not be fully supported without a typedef.")
    elif isinstance(current_type, c_ast.Enum):
        type_info['type_name'] = current_type.name if current_type.name else 'enum'
    else:
        type_info['type_name'] = str(type(current_type)) # Fallback for unhandled types

    return type_info

def generate_cbor_code(struct_defs):
    """
    Generates C header and source code for CBOR encoding/decoding.
    """
    header_template = env.get_template('cbor_generated.h.jinja')
    source_template = env.get_template('cbor_generated.c.jinja')

    # Prepare data for templates
    # For each struct, extract members with their processed type info
    processed_structs = []
    for struct_name, struct_node in struct_defs.items():
        members = []
        if struct_node.decls:
            for decl in struct_node.decls:
                if isinstance(decl, c_ast.Decl):
                    member_info = _get_c_type_info(decl)
                    member_info['name'] = decl.name
                    members.append(member_info)
                elif isinstance(decl, c_ast.Typedef):
                    # Typedefs within structs are not directly members to encode/decode
                    logger.warning(f"Skipping typedef '{decl.name}' inside struct '{struct_name}'.")
                elif isinstance(decl, c_ast.FuncDecl):
                    logger.warning(f"Skipping function pointer '{decl.name}' inside struct '{struct_name}'.")
                else:
                    logger.warning(f"Skipping unsupported declaration type {type(decl)} inside struct '{struct_name}'.")
        processed_structs.append({
            'name': struct_name,
            'members': members
        })
    
    # Render templates
    header_content = header_template.render(structs=processed_structs)
    source_content = source_template.render(structs=processed_structs)

    return header_content, source_content

# --- Main Script Logic ---

def main():
    parser = argparse.ArgumentParser(description="Generate CBOR encode/decode C code for structs.")
    parser.add_argument("header_file", help="Path to the C header file containing struct definitions.")
    parser.add_argument("--output-dir", default=".", help="Directory to output generated C files.")
    parser.add_argument("--cpp-path", default="gcc", help="Path to the C preprocessor (e.g., 'gcc', 'clang').")
    parser.add_argument("--cpp-args", nargs=argparse.REMAINDER,
                        help="Additional arguments to pass to the C preprocessor (e.g., -I<include_path>).")

    args = parser.parse_args()

    if not os.path.exists(args.header_file):
        logger.error(f"Header file not found: {args.header_file}")
        sys.exit(1)

    # Add the header file's directory to cpp_args if not already present
    header_dir = os.path.dirname(os.path.abspath(args.header_file))
    if args.cpp_args is None:
        args.cpp_args = []
    if f"-I{header_dir}" not in args.cpp_args and f"-I {header_dir}" not in args.cpp_args:
        args.cpp_args.append(f"-I{header_dir}")

    logger.info(f"Parsing C header file: {args.header_file}")
    try:
        # Use parse_file for actual file parsing with preprocessor
        ast = parse_file(
            args.header_file,
            use_cpp=True,
            cpp_path=args.cpp_path,
            cpp_args=args.cpp_args
        )
    except c_parser.ParseError as e:
        logger.error(f"Error parsing C header file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred during parsing: {e}")
        sys.exit(1)

    struct_definitions = {}
    for ext in ast.ext:
        if isinstance(ext, c_ast.Decl) and isinstance(ext.type, c_ast.Struct):
            if ext.type.name: # Only process named structs
                struct_definitions[ext.type.name] = ext.type
            else: # Anonymous struct declared directly, e.g., `struct { int x; } anon_var;`
                logger.warning(f"Skipping anonymous struct declaration without a name: {ext.name}")
        elif isinstance(ext, c_ast.Typedef):
            # Handle typedefs that define structs, e.g., `typedef struct { int x; } Point;`
            if isinstance(ext.type, c_ast.TypeDecl) and isinstance(ext.type.type, c_ast.Struct):
                if ext.name: # Ensure the typedef has a name
                    # Create a deep copy of the anonymous struct node and assign the typedef name to it.
                    # This ensures the struct_definitions map contains properly named structs
                    # without modifying the original AST, which is used by TypedefResolver.
                    named_struct_node = copy.deepcopy(ext.type.type)
                    if named_struct_node.name is None:
                        named_struct_node.name = ext.name
                    struct_definitions[ext.name] = named_struct_node
                else:
                    logger.warning(f"Skipping anonymous typedef struct without a name.")
            # Also handle typedefs of already named structs, e.g., `typedef struct MyStruct MyStruct_t;`
            elif isinstance(ext.type, c_ast.TypeDecl) and isinstance(ext.type.type, c_ast.IdentifierType):
                pass # These are handled by TypedefResolver during member expansion
            else:
                logger.info(f"Skipping typedef of type {type(ext.type.type).__name__} named '{ext.name}'.")
        else:
            logger.info(f"Skipping top-level declaration of type {type(ext).__name__}.")

    if not struct_definitions:
        logger.warning("No struct definitions found in the header file.")
        sys.exit(0)

    logger.info("Expanding typedefs within struct definitions...")
    # Expand typedefs within each struct's members
    for struct_name, struct_node in struct_definitions.items():
        _expand_in_place(struct_node, ast) # Pass the full AST for typedef resolution

    logger.info(f"Found {len(struct_definitions)} structs: {', '.join(struct_definitions.keys())}")

    header_content, source_content = generate_cbor_code(struct_definitions)

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    header_path = os.path.join(output_dir, "cbor_generated.h")
    source_path = os.path.join(output_dir, "cbor_generated.c")

    with open(header_path, "w") as f:
        f.write(header_content)
    logger.info(f"Generated header: {header_path}")

    with open(source_path, "w") as f:
        f.write(source_content)
    logger.info(f"Generated source: {source_path}")

if __name__ == '__main__':
    main()
