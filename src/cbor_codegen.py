import os
import logging
import argparse
from jinja2 import Environment, FileSystemLoader
from pycparser import c_parser, c_ast, parse_file

logger = logging.getLogger(__name__)

script_dir = os.path.dirname(os.path.abspath(__file__))
templates_dir = os.path.join(script_dir, '..', 'templates') # Adjust path to templates
env = Environment(loader=FileSystemLoader(templates_dir), trim_blocks=True, lstrip_blocks=True)

# --- Add parse_c_string function if not already present in src/cbor_codegen.py ---
# This function is crucial for parsing the input C header file.
def parse_c_string(c_code, cpp_path=None, cpp_args=None):
    """
    Parses a C code string into a pycparser AST.
    Args:
        c_code (str): The C code string to parse.
        cpp_path (str, optional): Path to the C preprocessor. Defaults to 'gcc'.
        cpp_args (list, optional): List of arguments to pass to the C preprocessor.
                                   Defaults to ['-E'].
    Returns:
        c_ast.FileAST: The parsed AST.
    """
    parser = c_parser.CParser()
    try:
        # pycparser expects a file, so we use parse_file with a dummy filename
        # and provide the c_code via the `text` argument.
        # It also needs a preprocessor.
        ast = parse_file(
            filename='<stdin>',
            text=c_code,
            parser=parser,
            use_cpp=True,
            cpp_path=cpp_path if cpp_path else 'gcc',
            cpp_args=cpp_args if cpp_args else ['-E']
        )
        return ast
    except c_parser.ParseError as e:
        logger.error(f"Error parsing C code: {e}")
        raise
# --- End of parse_c_string addition ---

# Existing functions like _find_struct, _find_typedef, _expand_in_place,
# _extract_base_type_info, generate_cbor_code_for_struct are assumed to be present
# and correctly implemented based on previous context.
# Placeholder for these functions. In a real scenario, their full content would be here.

def _find_struct(name, ast):
    """
    Finds a struct definition by name in the AST.
    (Placeholder - actual implementation would be here)
    """
    for node in ast.ext:
        if isinstance(node, c_ast.Decl) and isinstance(node.type, c_ast.Struct) and node.type.name == name:
            return node.type
        elif isinstance(node, c_ast.Typedef) and isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.Struct) and node.name == name:
            return node.type.type
    return None

def _find_typedef(name, ast):
    """
    Finds a typedef definition by name in the AST.
    (Placeholder - actual implementation would be here)
    """
    for node in ast.ext:
        if isinstance(node, c_ast.Typedef) and node.name == name:
            return node
    return None

def _extract_base_type_info(type_node, ast):
    """
    Extracts base type information (name, pointer status, array size) from a type node.
    (Placeholder - actual implementation would be here)
    """
    is_pointer = False
    array_size = None
    type_name = None
    is_struct = False

    current_type = type_node
    while True:
        if isinstance(current_type, c_ast.PtrDecl):
            is_pointer = True
            current_type = current_type.type
        elif isinstance(current_type, c_ast.ArrayDecl):
            if current_type.dim:
                # Attempt to evaluate the dimension if it's a constant
                try:
                    # pycparser's Constant node stores value as string
                    array_size = int(current_type.dim.value)
                except (AttributeError, ValueError):
                    logger.warning(f"Could not determine array size for {type_node.coord}. Assuming dynamic or unknown size.")
                    array_size = None # Cannot determine fixed size
            current_type = current_type.type
        elif isinstance(current_type, c_ast.TypeDecl):
            current_type = current_type.type
        elif isinstance(current_type, c_ast.IdentifierType):
            type_name = ' '.join(current_type.names)
            # Resolve typedefs
            typedef_node = _find_typedef(type_name, ast)
            if typedef_node:
                # Recursively get the base type of the typedef
                base_info = _extract_base_type_info(typedef_node.type, ast)
                type_name = base_info['type_name']
                is_struct = base_info['is_struct']
            break
        elif isinstance(current_type, c_ast.Struct):
            type_name = current_type.name
            is_struct = True
            break
        else:
            # Handle other cases like FuncDecl, etc., or break if unknown
            type_name = "UNKNOWN"
            break
    
    # Special handling for char arrays/pointers
    if type_name == 'char' and array_size is not None:
        # For char arrays, we treat them as text strings
        pass
    elif type_name == 'char' and is_pointer:
        # For char pointers, we treat them as text strings
        pass

    return {
        'type_name': type_name,
        'is_pointer': is_pointer,
        'array_size': array_size,
        'is_struct': is_struct
    }

def _expand_in_place(struct_node, ast):
    """
    Expands a struct definition in-place by resolving typedefs and nested structs.
    This function modifies the struct_node directly.
    (Placeholder - actual implementation would be here)
    """
    if not struct_node.decls:
        return # Nothing to expand if no declarations

    expanded_decls = []
    for decl in struct_node.decls:
        if isinstance(decl, c_ast.Decl):
            member_name = decl.name
            type_info = _extract_base_type_info(decl.type, ast)
            
            # If the member is a struct, ensure its definition is available
            if type_info['is_struct'] and type_info['type_name'] != struct_node.name: # Avoid infinite recursion for self-referential structs
                nested_struct_def = _find_struct(type_info['type_name'], ast)
                if nested_struct_def and not nested_struct_def.decls:
                    # If the nested struct is just a forward declaration, try to find its full definition
                    # This is a simplification; a more robust solution might involve a global struct registry
                    logger.warning(f"Nested struct '{type_info['type_name']}' in '{struct_node.name}' is a forward declaration. Full definition might be missing.")
                
                # Recursively expand nested structs if they are not pointers
                if not type_info['is_pointer'] and nested_struct_def:
                    _expand_in_place(nested_struct_def, ast)
            
            # Update the decl with expanded type info if necessary
            # For this simplified example, we just ensure type_info is correctly extracted.
            # The actual modification of decl.type for full expansion is complex and depends on pycparser AST manipulation.
            # For now, we rely on _extract_base_type_info to give us the 'final' type name.
            
            # Store the extracted info directly on the decl object for easier access later
            decl._type_info = type_info
            expanded_decls.append(decl)
        else:
            expanded_decls.append(decl) # Keep non-Decl nodes as is

    struct_node.decls = expanded_decls


def generate_cbor_code_for_struct(struct_node, ast):
    """
    Generates CBOR encoding/decoding code for a single struct.
    (Placeholder - actual implementation would be here)
    """
    if not struct_node.name:
        return None # Skip anonymous structs

    members = []
    if struct_node.decls:
        for decl in struct_node.decls:
            if isinstance(decl, c_ast.Decl):
                # Use the pre-extracted type info from _expand_in_place
                type_info = getattr(decl, '_type_info', _extract_base_type_info(decl.type, ast))
                
                # Skip function pointers
                if isinstance(decl.type, c_ast.FuncDecl):
                    logger.warning(f"Skipping function pointer '{decl.name}' in struct '{struct_node.name}'.")
                    continue

                members.append({
                    'name': decl.name,
                    'type_name': type_info['type_name'],
                    'is_pointer': type_info['is_pointer'],
                    'array_size': type_info['array_size'],
                    'is_struct': type_info['is_struct']
                })
            elif isinstance(decl, c_ast.Typedef):
                logger.warning(f"Skipping typedef '{decl.name}' inside struct '{struct_node.name}'. Typedefs should be top-level.")
            else:
                logger.warning(f"Skipping unsupported declaration type in struct '{struct_node.name}': {type(decl)}")

    return {
        'c_implementation': {
            'name': struct_node.name,
            'members': members
        },
        'encode_prototype': f"bool encode_{struct_node.name}(const struct {struct_node.name}* data, CborEncoder* encoder);",
        'decode_prototype': f"bool decode_{struct_node.name}(struct {struct_node.name}* data, CborValue* it);"
    }


# Modify the main function
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
    all_struct_c_implementations = []
    all_struct_h_prototypes = []

    # Find all struct definitions and generate code
    for node in file_ast.ext:
        if isinstance(node, c_ast.Decl) and isinstance(node.type, c_ast.Struct):
            struct_node = node.type
            if struct_node.name: # Only process named structs
                logger.info(f"Generating code for struct: {struct_node.name}")
                
                # Ensure struct is fully expanded before generating code
                # This modifies struct_node in place by resolving typedefs and nested structs
                _expand_in_place(struct_node, file_ast) 

                generated_code = generate_cbor_code_for_struct(struct_node, file_ast)
                if generated_code:
                    all_struct_c_implementations.append(generated_code['c_implementation'])
                    all_struct_h_prototypes.append(generated_code['c_implementation']) # Pass the full struct dict for H template
            else:
                logger.debug(f"Skipping anonymous struct at {node.coord}")
        elif isinstance(node, c_ast.Typedef) and isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.Struct):
            # Handle typedef'd structs like `typedef struct MyStruct { ... } MyStruct;`
            struct_node = node.type.type
            if struct_node.name: # Use the struct's internal name if available
                logger.info(f"Generating code for typedef'd struct: {struct_node.name} (typedef: {node.name})")
                _expand_in_place(struct_node, file_ast)
                generated_code = generate_cbor_code_for_struct(struct_node, file_ast)
                if generated_code:
                    all_struct_c_implementations.append(generated_code['c_implementation'])
                    all_struct_h_prototypes.append(generated_code['c_implementation'])
            else: # Handle `typedef struct { ... } MyStruct;` (anonymous struct with typedef name)
                struct_node.name = node.name # Assign the typedef name to the struct for processing
                logger.info(f"Generating code for anonymous struct via typedef: {struct_node.name}")
                _expand_in_place(struct_node, file_ast)
                generated_code = generate_cbor_code_for_struct(struct_node, file_ast)
                if generated_code:
                    all_struct_c_implementations.append(generated_code['c_implementation'])
                    all_struct_h_prototypes.append(generated_code['c_implementation'])
        else:
            logger.debug(f"Skipping non-struct/typedef node: {type(node).__name__} at {getattr(node, 'coord', 'N/A')}")


    # Render cbor_generated.h
    h_template = env.get_template('cbor_generated.h.jinja')
    rendered_h = h_template.render(structs=all_struct_h_prototypes)
    with open(os.path.join(output_dir, 'cbor_generated.h'), 'w') as f:
        f.write(rendered_h)
    logger.info(f"Generated {os.path.join(output_dir, 'cbor_generated.h')}")

    # Render cbor_generated.c
    c_template = env.get_template('cbor_generated.c.jinja')
    rendered_c = c_template.render(structs=all_struct_c_implementations) # Changed context variable name to 'structs'
    with open(os.path.join(output_dir, 'cbor_generated.c'), 'w') as f:
        f.write(rendered_c)
    logger.info(f"Generated {os.path.join(output_dir, 'cbor_generated.c')}")

    # Render CMakeLists.txt
    cmake_template = env.get_template('CMakeLists.txt.jinja')
    rendered_cmake = cmake_template.render(
        generated_library_name="cbor_generated",
        generated_c_file_name="cbor_generated.c",
        input_header_path=os.path.abspath(args.input_header), # Pass full path to input header
        output_dir_path=os.path.abspath(output_dir) # Pass full path to output dir
    )
    with open(os.path.join(output_dir, 'CMakeLists.txt'), 'w') as f:
        f.write(rendered_cmake)
    logger.info(f"Generated {os.path.join(output_dir, 'CMakeLists.txt')}")

    logger.info(f"CBOR code generation complete. Output in: {output_dir}")

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    main()
