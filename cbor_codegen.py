import sys
import argparse
import os
import copy

# This is not required if you've installed pycparser into
# your site-packages/ with setup.py
sys.path.extend([".", ".."])

from pycparser import c_parser, c_ast, parse_file

# --- Helper functions for AST traversal and type expansion ---


def _find_struct(name, file_ast):
    """Receives a struct name and returns the declared struct object from file_ast."""
    for node in file_ast.ext:
        if (
            isinstance(node, c_ast.Decl)
            and isinstance(node.type, c_ast.Struct)
            and node.type.name == name
            and node.type.decls is not None
        ):  # Ensure it's a definition, not just a declaration
            return node.type
        elif (
            isinstance(node, c_ast.Typedef)
            and isinstance(node.type, c_ast.TypeDecl)
            and isinstance(node.type.type, c_ast.Struct)
            and node.type.type.name == name
            and node.type.type.decls is not None
        ):
            return node.type.type
    return None


def _find_typedef(name, file_ast):
    """Receives a type name and returns the typedef object from file_ast."""
    for node in file_ast.ext:
        if isinstance(node, c_ast.Typedef) and node.name == name:
            return node
    return None


def _expand_in_place(type_node, file_ast, expand_struct=True, expand_typedef=True):
    """Recursively expands struct & typedef in a type node.
    Returns the expanded type node.
    """
    if isinstance(type_node, c_ast.TypeDecl):
        type_node.type = _expand_in_place(
            type_node.type, file_ast, expand_struct, expand_typedef
        )
    elif isinstance(type_node, c_ast.PtrDecl):
        type_node.type = _expand_in_place(
            type_node.type, file_ast, expand_struct, expand_typedef
        )
    elif isinstance(type_node, c_ast.ArrayDecl):
        type_node.type = _expand_in_place(
            type_node.type, file_ast, expand_struct, expand_typedef
        )
    elif isinstance(type_node, c_ast.FuncDecl):
        type_node.type = _expand_in_place(
            type_node.type, file_ast, expand_struct, expand_typedef
        )
        if type_node.args:
            for i, param in enumerate(type_node.args.params):
                # Parameters are Decl nodes, need to expand their types
                param.type = _expand_in_place(
                    param.type, file_ast, expand_struct, expand_typedef
                )
    elif isinstance(type_node, c_ast.Struct):
        # If it's a struct declaration without definition, find its definition
        if (
            type_node.decls is None
        ):  # `decls` is None for forward declarations or just `struct S;`
            struct_def = _find_struct(type_node.name, file_ast)
            if struct_def:
                type_node.decls = struct_def.decls  # Copy members from definition
            else:
                raise RuntimeError(f"using undeclared struct {type_node.name}")

        # Recursively expand members if requested (always for codegen)
        if expand_struct and type_node.decls:
            for i, mem_decl in enumerate(type_node.decls):
                # mem_decl is a c_ast.Decl, its type is mem_decl.type
                mem_decl.type = _expand_in_place(
                    mem_decl.type, file_ast, expand_struct, expand_typedef
                )
    elif isinstance(type_node, c_ast.IdentifierType):
        # Check if it's a typedef
        typedef_name = type_node.names[0]
        typedef_def = _find_typedef(typedef_name, file_ast)
        if typedef_def:
            if expand_typedef:
                # Replace IdentifierType with the expanded typedef's type
                return _expand_in_place(
                    copy.deepcopy(typedef_def.type),
                    file_ast,
                    expand_struct,
                    expand_typedef,
                )
            # If not expanding, keep the IdentifierType as is

    return type_node


def _get_c_type_string_for_cast(c_type_node):
    """
    Converts a pycparser type node into its C string representation suitable for casting.
    This is used when casting a uint64_t/int64_t to the actual member type.
    It strips pointers and array dimensions to get the fundamental type.
    """
    if isinstance(c_type_node, c_ast.TypeDecl):
        quals = " ".join(c_type_node.quals) + " " if c_type_node.quals else ""
        return quals + _get_c_type_string_for_cast(c_type_node.type)
    elif isinstance(c_type_node, c_ast.PtrDecl):
        return _get_c_type_string_for_cast(c_type_node.type)
    elif isinstance(c_type_node, c_ast.ArrayDecl):
        return _get_c_type_string_for_cast(c_type_node.type)
    elif isinstance(c_type_node, c_ast.FuncDecl):
        return "void"
    elif isinstance(c_type_node, c_ast.IdentifierType):
        if "bool" in c_type_node.names:
            return "bool"
        return " ".join(c_type_node.names)
    elif isinstance(c_type_node, c_ast.Struct):
        return f"struct {c_type_node.name}" if c_type_node.name else "struct"
    elif isinstance(c_type_node, c_ast.Decl):
        return _get_c_type_string_for_cast(c_type_node.type)
    elif isinstance(c_type_node, c_ast.Typename):
        return _get_c_type_string_for_cast(c_type_node.type)
    return "void"  # Default for unknown types


def _extract_base_type_info(type_node, file_ast):
    """
    Extracts detailed information about a C type node.
    Returns a dictionary with keys like 'base_type_names', 'is_pointer', 'is_array', etc.
    """
    quals = []
    is_pointer = 0
    is_array = False
    array_dims = []
    is_struct = False
    struct_name = None
    is_func_ptr = False
    base_type_names = []
    struct_def_node = None

    # First, deepcopy and expand the type node to resolve typedefs and struct definitions
    try:
        expanded_type = _expand_in_place(
            copy.deepcopy(type_node), file_ast, expand_struct=True, expand_typedef=True
        )
    except RuntimeError as e:
        print(
            f"Warning: Could not fully expand type for {type_node.__class__.__name__}: {e}",
            file=sys.stderr,
        )
        expanded_type = type_node  # Fallback to unexpanded if error

    current_node = expanded_type
    while True:
        if isinstance(current_node, c_ast.TypeDecl):
            quals.extend(current_node.quals)
            current_node = current_node.type
        elif isinstance(current_node, c_ast.PtrDecl):
            quals.extend(current_node.quals)
            is_pointer += 1
            current_node = current_node.type
        elif isinstance(current_node, c_ast.ArrayDecl):
            is_array = True
            if current_node.dim:
                array_dims.append(current_node.dim.value)
            else:
                array_dims.append("")  # Indefinite length array
            current_node = current_node.type
        elif isinstance(current_node, c_ast.FuncDecl):
            is_func_ptr = True
            base_type_names = ["void"]
            is_pointer = 1  # Treat as a pointer to void
            break
        elif isinstance(current_node, c_ast.IdentifierType):
            # Check for both 'bool' and '_Bool' (which 'bool' often expands to from stdbool.h)
            if "bool" in current_node.names or "_Bool" in current_node.names:
                base_type_names = ["bool"]  # Standardize to "bool" for internal logic
            else:
                base_type_names = current_node.names
            break
        elif isinstance(current_node, c_ast.Struct):
            is_struct = True
            struct_name = current_node.name
            base_type_names = ["struct", struct_name]
            struct_def_node = (
                current_node  # This is the expanded struct node with decls
            )
            break
        elif isinstance(current_node, c_ast.Typename):
            base_type_names = [current_node.name]
            break
        else:
            base_type_names = ["UNKNOWN_TYPE"]
            break

    quals_set = set(quals)

    return {
        "base_type_names": base_type_names,
        "is_pointer": is_pointer,
        "is_array": is_array,
        "array_dims": array_dims,
        "is_struct": is_struct,
        "struct_name": struct_name,
        "is_const": "const" in quals_set,
        "is_unsigned": "unsigned" in quals_set,
        "is_signed": "signed" in quals_set,
        "is_func_ptr": is_func_ptr,
        "struct_def_node": struct_def_node,
        "original_type_node": type_node,  # Keep original for _get_c_type_string_for_cast
    }


def generate_cbor_code_for_struct(struct_node, file_ast):
    """
    Generates C code for encoding and decoding a single struct.
    Returns a tuple: (header_code_str, source_code_str)
    """
    struct_name = struct_node.name
    if not struct_name:
        print("Warning: Skipping anonymous struct definition.", file=sys.stderr)
        return "", ""

    # Add this check to prevent TypeError if decls is None
    if struct_node.decls is None:
        print(f"Warning: Skipping struct '{struct_name}' as its definition (members) could not be found.", file=sys.stderr)
        return "", ""

    encode_func_name = f"encode_{struct_name}"
    decode_func_name = f"decode_{struct_name}"

    header_code = []
    source_code = []

    # --- Header Code ---
    header_code.append(
        f"bool {encode_func_name}(const struct {struct_name}* data, CborEncoder* encoder);"
    )
    header_code.append(
        f"bool {decode_func_name}(struct {struct_name}* data, CborValue* it);"
    )
    header_code.append("")

    # --- Source Code - Encode Function ---
    source_code.append(
        f"bool {encode_func_name}(const struct {struct_name}* data, CborEncoder* encoder) {{"
    )
    source_code.append("    CborError err;")
    source_code.append(f"    CborEncoder mapEncoder;")
    source_code.append("")
    source_code.append(f"    if (!data) {{")
    source_code.append(f"        return cbor_encode_null(encoder) == CborNoError;")
    source_code.append(f"    }}")
    source_code.append("")
    source_code.append(
        f"    err = cbor_encoder_create_map(encoder, &mapEncoder, {len(struct_node.decls)});"
    )
    source_code.append(f"    if (err != CborNoError) return false;")
    source_code.append("")

    for member_decl in struct_node.decls:
        member_name = member_decl.name
        if not member_name:
            print(
                f"Warning: Skipping anonymous member in struct '{struct_name}'.",
                file=sys.stderr,
            )
            continue

        member_type_info = _extract_base_type_info(member_decl.type, file_ast)

        # Skip function pointers for now
        if member_type_info["is_func_ptr"]:
            print(
                f"Warning: Skipping function pointer member '{member_name}' in struct '{struct_name}' for CBOR codegen.",
                file=sys.stderr,
            )
            continue

        # Encode key (member name)
        source_code.append(
            f'    err = cbor_encode_text_stringz(&mapEncoder, "{member_name}");'
        )
        source_code.append(f"    if (err != CborNoError) return false;")

        # Encode value based on type
        if member_type_info["is_pointer"] > 0:
            # Handle pointers: encode NULL as CBOR null, otherwise dereference
            source_code.append(f"    if (!data->{member_name}) {{")
            source_code.append(f"        err = cbor_encode_null(&mapEncoder);")
            source_code.append(f"        if (err != CborNoError) return false;")
            source_code.append(f"    }} else {{")
            # For pointers, we need to dereference or handle as string/struct
            if member_type_info["is_struct"]:
                # Nested struct pointer
                source_code.append(
                    f"        if (!encode_{member_type_info['struct_name']}(data->{member_name}, &mapEncoder)) return false;"
                )
            elif (
                "char" in member_type_info["base_type_names"]
                and member_type_info["is_pointer"] == 1
            ):
                # char* as null-terminated string
                source_code.append(
                    f"        err = cbor_encode_text_stringz(&mapEncoder, data->{member_name});"
                )
                source_code.append(f"        if (err != CborNoError) return false;")
            else:
                # Pointer to basic type, dereference
                cast_type = _get_c_type_string_for_cast(
                    member_type_info["original_type_node"]
                )
                if (
                    "int" in member_type_info["base_type_names"]
                    or "char" in member_type_info["base_type_names"]
                ):
                    if member_type_info["is_unsigned"]:
                        source_code.append(
                            f"        err = cbor_encode_uint(&mapEncoder, (uint64_t)*data->{member_name});"
                        )
                    else:
                        source_code.append(
                            f"        err = cbor_encode_int(&mapEncoder, (int64_t)*data->{member_name});"
                        )
                elif "float" in member_type_info["base_type_names"]:
                    source_code.append(
                        f"        err = cbor_encode_float(&mapEncoder, *data->{member_name});"
                    )
                elif "double" in member_type_info["base_type_names"]:
                    source_code.append(
                        f"        err = cbor_encode_double(&mapEncoder, *data->{member_name});"
                    )
                elif "bool" in member_type_info["base_type_names"]:
                    source_code.append(
                        f"        err = cbor_encode_boolean(&mapEncoder, *data->{member_name});"
                    )
                else:
                    print(
                        f"Warning: Unsupported pointer type for member '{member_name}' in struct '{struct_name}'. Encoding as null.",
                        file=sys.stderr,
                    )
                    source_code.append(f"        err = cbor_encode_null(&mapEncoder);")
                source_code.append(f"        if (err != CborNoError) return false;")
            source_code.append(f"    }}")  # End of if (!data->member)
        elif member_type_info["is_array"]:
            # Handle arrays
            if (
                "char" in member_type_info["base_type_names"]
                and len(member_type_info["array_dims"]) == 1
            ):
                # char array as string (e.g., char name[64])
                source_code.append(
                    f"    err = cbor_encode_text_string(&mapEncoder, (const char*)data->{member_name}, strlen((const char*)data->{member_name}));"
                )
                source_code.append(f"    if (err != CborNoError) return false;")
            else:
                # Array of other types or multi-dimensional arrays
                # Encode as CBOR array
                array_len_str = member_type_info["array_dims"][
                    0
                ]  # Assuming 1D array for simplicity
                if not array_len_str:
                    print(
                        f"Warning: Skipping indefinite length array member '{member_name}' in struct '{struct_name}'. Requires manual handling.",
                        file=sys.stderr,
                    )
                    continue  # Skip for now, or encode as empty array

                source_code.append(f"    CborEncoder arrayEncoder_{member_name};")
                source_code.append(
                    f"    err = cbor_encoder_create_array(&mapEncoder, &arrayEncoder_{member_name}, {array_len_str});"
                )
                source_code.append(f"    if (err != CborNoError) return false;")
                source_code.append(
                    f"    for (size_t i = 0; i < {array_len_str}; ++i) {{"
                )

                # Determine element type by traversing down the array decls
                element_type_node = member_decl.type
                for _ in range(len(member_type_info["array_dims"])):
                    if isinstance(element_type_node, c_ast.ArrayDecl) or isinstance(
                        element_type_node, c_ast.TypeDecl
                    ):
                        element_type_node = element_type_node.type
                    else:
                        break  # Should not happen if array_dims is correct

                element_type_info = _extract_base_type_info(element_type_node, file_ast)
                cast_type = _get_c_type_string_for_cast(
                    element_type_info["original_type_node"]
                )

                if element_type_info["is_struct"]:
                    source_code.append(
                        f"        if (!encode_{element_type_info['struct_name']}(&data->{member_name}[i], &arrayEncoder_{member_name})) return false;"
                    )
                elif (
                    "int" in element_type_info["base_type_names"]
                    or "char" in element_type_info["base_type_names"]
                ):
                    if element_type_info["is_unsigned"]:
                        source_code.append(
                            f"        err = cbor_encode_uint(&arrayEncoder_{member_name}, (uint64_t)data->{member_name}[i]);"
                        )
                    else:
                        source_code.append(
                            f"        err = cbor_encode_int(&arrayEncoder_{member_name}, (int64_t)data->{member_name}[i]);"
                        )
                elif "float" in element_type_info["base_type_names"]:
                    source_code.append(
                        f"        err = cbor_encode_float(&arrayEncoder_{member_name}, data->{member_name}[i]);"
                    )
                elif "double" in element_type_info["base_type_names"]:
                    source_code.append(
                        f"        err = cbor_encode_double(&arrayEncoder_{member_name}, data->{member_name}[i]);"
                    )
                elif "bool" in element_type_info["base_type_names"]:
                    source_code.append(
                        f"        err = cbor_encode_boolean(&arrayEncoder_{member_name}, data->{member_name}[i]);"
                    )
                else:
                    print(
                        f"Warning: Unsupported array element type for member '{member_name}' in struct '{struct_name}'. Encoding as null.",
                        file=sys.stderr,
                    )
                    source_code.append(
                        f"        err = cbor_encode_null(&arrayEncoder_{member_name});"
                    )
                source_code.append(f"        if (err != CborNoError) return false;")
                source_code.append(f"    }}")  # End of for loop
                source_code.append(
                    f"    err = cbor_encoder_close_container(&mapEncoder, &arrayEncoder_{member_name});"
                )
                source_code.append(f"    if (err != CborNoError) return false;")
        elif member_type_info["is_struct"]:
            # Nested struct
            source_code.append(
                f"    if (!encode_{member_type_info['struct_name']}(&data->{member_name}, &mapEncoder)) return false;"
            )
        elif "bool" in member_type_info["base_type_names"]:
            # Basic type: bool
            source_code.append(
                f"    err = cbor_encode_boolean(&mapEncoder, data->{member_name});"
            )
            source_code.append(f"    if (err != CborNoError) return false;")
        else:
            # Basic type
            cast_type = _get_c_type_string_for_cast(
                member_type_info["original_type_node"]
            )
            if (
                "int" in member_type_info["base_type_names"]
                or "char" in member_type_info["base_type_names"]
            ):
                if member_type_info["is_unsigned"]:
                    source_code.append(
                        f"    err = cbor_encode_uint(&mapEncoder, (uint64_t)data->{member_name});"
                    )
                else:
                    source_code.append(
                        f"    err = cbor_encode_int(&mapEncoder, (int64_t)data->{member_name});"
                    )
            elif "float" in member_type_info["base_type_names"]:
                source_code.append(
                    f"    err = cbor_encode_float(&mapEncoder, data->{member_name});"
                )
            elif "double" in member_type_info["base_type_names"]:
                source_code.append(
                    f"    err = cbor_encode_double(&mapEncoder, data->{member_name});"
                )
            else:
                print(
                    f"Warning: Unsupported basic type for member '{member_name}' in struct '{struct_name}'. Encoding as null.",
                    file=sys.stderr,
                )
                source_code.append(f"    err = cbor_encode_null(&mapEncoder);")
            source_code.append(f"    if (err != CborNoError) return false;")

    source_code.append("")
    source_code.append(f"    err = cbor_encoder_close_container(encoder, &mapEncoder);")
    source_code.append(f"    if (err != CborNoError) return false;")
    source_code.append(f"    return true;")
    source_code.append(f"}}")
    source_code.append("")

    # --- Source Code - Decode Function ---
    source_code.append(
        f"bool {decode_func_name}(struct {struct_name}* data, CborValue* it) {{"
    )
    source_code.append("    CborError err;")
    source_code.append(f"    CborValue mapIt;")
    source_code.append(f"    size_t num_elements;")
    source_code.append("")
    source_code.append(f"    if (cbor_value_is_null(it)) {{")
    source_code.append(
        f"        // If the encoded value is null, set data to default or indicate null."
    )
    source_code.append(
        f"        // For simplicity, we'll just advance and return true, assuming caller handles null data."
    )
    source_code.append(f"        err = cbor_value_advance(it);")
    source_code.append(f"        return err == CborNoError;")
    source_code.append(f"    }}")
    source_code.append("")
    source_code.append(f"    if (!cbor_value_is_map(it)) return false;")
    source_code.append("")
    source_code.append(f"    err = cbor_value_enter_container(it, &mapIt);")
    source_code.append(f"    if (err != CborNoError) return false;")
    source_code.append("")
    source_code.append(f"    // Iterate through map elements")
    source_code.append(f"    while (!cbor_value_at_end(&mapIt)) {{")
    source_code.append(
        f"        if (!cbor_value_is_text_string(&mapIt)) return false; // Key must be a text string"
    )
    source_code.append("")
    source_code.append(f"        // Check for each member")

    for member_decl in struct_node.decls:
        member_name = member_decl.name
        if not member_name:
            continue

        member_type_info = _extract_base_type_info(member_decl.type, file_ast)

        if member_type_info["is_func_ptr"]:
            continue  # Skip function pointers

        source_code.append(
            f'        if (cbor_value_text_string_equals(&mapIt, "{member_name}", &num_elements)) {{'
        )
        source_code.append(f"            err = cbor_value_advance(&mapIt);")
        source_code.append(f"            if (err != CborNoError) return false;")

        # Decode value based on type
        if member_type_info["is_pointer"] > 0:
            # Handle pointers: check for null, otherwise decode into dereferenced location
            source_code.append(f"            if (cbor_value_is_null(&mapIt)) {{")
            source_code.append(f"                data->{member_name} = NULL;")
            source_code.append(f"                err = cbor_value_advance(&mapIt);")
            source_code.append(f"                if (err != CborNoError) return false;")
            source_code.append(f"            }} else {{")
            if member_type_info["is_struct"]:
                # Nested struct pointer
                source_code.append(
                    f"                // WARNING: For struct pointers, memory for data->{member_name} must be allocated by caller."
                )
                source_code.append(
                    f"                if (!data->{member_name}) {{ /* Handle error or allocate */ return false; }}"
                )
                source_code.append(
                    f"                if (!decode_{member_type_info['struct_name']}(data->{member_name}, &mapIt)) return false;"
                )
            elif (
                "char" in member_type_info["base_type_names"]
                and member_type_info["is_pointer"] == 1
            ):
                # char* as null-terminated string
                source_code.append(
                    f"                // WARNING: For char* members, memory for data->{member_name} must be allocated by caller."
                )
                source_code.append(
                    f"                // This code assumes the buffer is already allocated and large enough."
                )
                source_code.append(
                    f"                if (!data->{member_name}) {{ /* Handle error or allocate */ return false; }}"
                )
                source_code.append(f"                size_t actual_len_{member_name};")
                source_code.append(
                    f"                err = cbor_value_get_string_length(&mapIt, &actual_len_{member_name});"
                )
                source_code.append(
                    f"                if (err != CborNoError) return false;"
                )
                source_code.append(
                    f"                err = cbor_value_copy_text_string(&mapIt, data->{member_name}, &actual_len_{member_name}, &mapIt);"
                )
                source_code.append(
                    f"                if (err != CborNoError) return false;"
                )
            else:
                # Pointer to basic type, decode into dereferenced location
                source_code.append(
                    f"                // WARNING: For basic type pointers, memory for data->{member_name} must be allocated by caller."
                )
                source_code.append(
                    f"                if (!data->{member_name}) {{ /* Handle error or allocate */ return false; }}"
                )
                cast_type = _get_c_type_string_for_cast(
                    member_type_info["original_type_node"]
                )
                if (
                    "int" in member_type_info["base_type_names"]
                    or "char" in member_type_info["base_type_names"]
                ):
                    if member_type_info["is_unsigned"]:
                        source_code.append(f"                uint64_t temp_val;")
                        source_code.append(
                            f"                err = cbor_value_get_uint64(&mapIt, &temp_val);"
                        )
                        source_code.append(
                            f"                if (err != CborNoError) return false;"
                        )
                        source_code.append(
                            f"                *data->{member_name} = ({cast_type})temp_val;"
                        )
                    else:
                        source_code.append(f"                int64_t temp_val;")
                        source_code.append(
                            f"                err = cbor_value_get_int64(&mapIt, &temp_val);"
                        )
                        source_code.append(
                            f"                if (err != CborNoError) return false;"
                        )
                        source_code.append(
                            f"                *data->{member_name} = ({cast_type})temp_val;"
                        )
                elif "float" in member_type_info["base_type_names"]:
                    source_code.append(
                        f"                err = cbor_value_get_float(&mapIt, data->{member_name});"
                    )
                elif "double" in member_type_info["base_type_names"]:
                    source_code.append(
                        f"                err = cbor_value_get_double(&mapIt, data->{member_name});"
                    )
                elif "bool" in member_type_info["base_type_names"]:
                    source_code.append(
                        f"                err = cbor_value_get_boolean(&mapIt, data->{member_name});"
                    )
                else:
                    print(
                        f"Warning: Unsupported pointer type for member '{member_name}' in struct '{struct_name}'. Skipping decode.",
                        file=sys.stderr,
                    )
                    source_code.append(
                        f"                err = cbor_value_advance(&mapIt);"
                    )  # Advance to skip unknown type
                source_code.append(
                    f"                if (err != CborNoError) return false;"
                )
                source_code.append(
                    f"                // Value was advanced by get_X functions, no need for extra advance here."
                )
            source_code.append(
                f"            }}"
            )  # End of if (cbor_value_is_null(&mapIt))
        elif member_type_info["is_array"]:
            # Handle arrays
            if (
                "char" in member_type_info["base_type_names"]
                and len(member_type_info["array_dims"]) == 1
            ):
                # char array as string (e.g., char name[64])
                source_code.append(f"            size_t len_{member_name};")
                source_code.append(
                    f"            err = cbor_value_get_string_length(&mapIt, &len_{member_name});"
                )
                source_code.append(f"            if (err != CborNoError) return false;")
                source_code.append(
                    f"            if (len_{member_name} + 1 > sizeof(data->{member_name})) {{ /* Buffer too small */ return false; }}"
                )
                source_code.append(
                    f"            err = cbor_value_copy_text_string(&mapIt, data->{member_name}, &len_{member_name}, &mapIt);"
                )
                source_code.append(f"            if (err != CborNoError) return false;")
            else:
                # Array of other types or multi-dimensional arrays
                array_len_str = member_type_info["array_dims"][0]
                if not array_len_str:
                    print(
                        f"Warning: Skipping indefinite length array member '{member_name}' in struct '{struct_name}' for decoding. Requires manual handling.",
                        file=sys.stderr,
                    )
                    source_code.append(
                        f"            err = cbor_value_advance(&mapIt);"
                    )  # Advance to skip unknown type
                    source_code.append(
                        f"            if (err != CborNoError) return false;"
                    )
                    source_code.append(f"            continue;")  # Skip to next member

                source_code.append(f"            CborValue arrayIt_{member_name};")
                source_code.append(
                    f"            if (!cbor_value_is_array(&mapIt)) return false;"
                )
                source_code.append(
                    f"            err = cbor_value_enter_container(&mapIt, &arrayIt_{member_name});"
                )
                source_code.append(f"            if (err != CborNoError) return false;")
                source_code.append(
                    f"            for (size_t i = 0; i < {array_len_str}; ++i) {{"
                )
                source_code.append(
                    f"                if (cbor_value_at_end(&arrayIt_{member_name})) return false; // Not enough elements"
                )

                element_type_node = member_decl.type
                for _ in range(len(member_type_info["array_dims"])):
                    if isinstance(element_type_node, c_ast.ArrayDecl) or isinstance(
                        element_type_node, c_ast.TypeDecl
                    ):
                        element_type_node = element_type_node.type
                    else:
                        break  # Should not happen if array_dims is correct

                element_type_info = _extract_base_type_info(element_type_node, file_ast)
                cast_type = _get_c_type_string_for_cast(
                    element_type_info["original_type_node"]
                )

                if element_type_info["is_struct"]:
                    source_code.append(
                        f"                if (!decode_{element_type_info['struct_name']}(&data->{member_name}[i], &arrayIt_{member_name})) return false;"
                    )
                elif (
                    "int" in element_type_info["base_type_names"]
                    or "char" in element_type_info["base_type_names"]
                ):
                    if element_type_info["is_unsigned"]:
                        source_code.append(f"                uint64_t temp_val;")
                        source_code.append(
                            f"                err = cbor_value_get_uint64(&arrayIt_{member_name}, &temp_val);"
                        )
                        source_code.append(
                            f"                if (err != CborNoError) return false;"
                        )
                        source_code.append(
                            f"                data->{member_name}[i] = ({cast_type})temp_val;"
                        )
                    else:
                        source_code.append(f"                int64_t temp_val;")
                        source_code.append(
                            f"                err = cbor_value_get_int64(&arrayIt_{member_name}, &temp_val);"
                        )
                        source_code.append(
                            f"                if (err != CborNoError) return false;"
                        )
                        source_code.append(
                            f"                data->{member_name}[i] = ({cast_type})temp_val;"
                        )
                elif "float" in element_type_info["base_type_names"]:
                    source_code.append(
                        f"                err = cbor_value_get_float(&arrayIt_{member_name}, &data->{member_name}[i]);"
                    )
                elif "double" in element_type_info["base_type_names"]:
                    source_code.append(
                        f"                err = cbor_value_get_double(&arrayIt_{member_name}, &data->{member_name}[i]);"
                    )
                elif "bool" in element_type_info["base_type_names"]:
                    source_code.append(
                        f"                err = cbor_value_get_boolean(&arrayIt_{member_name}, &data->{member_name}[i]);"
                    )
                else:
                    print(
                        f"Warning: Unsupported array element type for member '{member_name}' in struct '{struct_name}'. Skipping decode.",
                        file=sys.stderr,
                    )
                    source_code.append(
                        f"                err = cbor_value_advance(&arrayIt_{member_name});"
                    )  # Advance to skip unknown type
                source_code.append(
                    f"                if (err != CborNoError) return false;"
                )
                source_code.append(f"            }}")  # End of for loop
                source_code.append(
                    f"            err = cbor_value_leave_container(&mapIt, &arrayIt_{member_name});"
                )
                source_code.append(f"            if (err != CborNoError) return false;")
        elif member_type_info["is_struct"]:
            # Nested struct
            source_code.append(
                f"            if (!decode_{member_type_info['struct_name']}(data->{member_name}, &mapIt)) return false;"
            )
        elif "bool" in member_type_info["base_type_names"]:
            # Basic type: bool
            source_code.append(
                f"            err = cbor_value_get_boolean(&mapIt, &data->{member_name});"
            )
            source_code.append(f"            if (err != CborNoError) return false;")
        else:
            # Basic type
            cast_type = _get_c_type_string_for_cast(
                member_type_info["original_type_node"]
            )
            if (
                "int" in member_type_info["base_type_names"]
                or "char" in member_type_info["base_type_names"]
            ):
                if member_type_info["is_unsigned"]:
                    source_code.append(f"            uint64_t temp_val;")
                    source_code.append(
                        f"            err = cbor_value_get_uint64(&mapIt, &temp_val);"
                    )
                    source_code.append(
                        f"            if (err != CborNoError) return false;"
                    )
                    source_code.append(
                        f"            data->{member_name} = ({cast_type})temp_val;"
                    )
                else:
                    source_code.append(f"            int64_t temp_val;")
                    source_code.append(
                        f"            err = cbor_value_get_int64(&mapIt, &temp_val);"
                    )
                    source_code.append(
                        f"            if (err != CborNoError) return false;"
                    )
                    source_code.append(
                        f"            data->{member_name} = ({cast_type})temp_val;"
                    )
            elif "float" in member_type_info["base_type_names"]:
                source_code.append(
                    f"            err = cbor_value_get_float(&mapIt, &data->{member_name});"
                )
            elif "double" in member_type_info["base_type_names"]:
                source_code.append(
                    f"            err = cbor_value_get_double(&mapIt, &data->{member_name});"
                )
            else:
                print(
                    f"Warning: Unsupported basic type for member '{member_name}' in struct '{struct_name}'. Skipping decode.",
                    file=sys.stderr,
                )
                source_code.append(
                    f"            err = cbor_value_advance(&mapIt);"
                )  # Advance to skip unknown type
            source_code.append(f"            if (err != CborNoError) return false;")
        source_code.append(f"        }} else {{")
        source_code.append(f"            // Unknown key, skip it and its value")
        source_code.append(f"            err = cbor_value_advance(&mapIt);")
        source_code.append(f"            if (err != CborNoError) return false;")
        source_code.append(f"            err = cbor_value_advance(&mapIt);")
        source_code.append(f"            if (err != CborNoError) return false;")
        source_code.append(f"        }}")  # End of if (cbor_value_text_string_equals)
    source_code.append(f"    }}")  # End of while loop
    source_code.append("")
    source_code.append(f"    err = cbor_value_leave_container(it, &mapIt);")
    source_code.append(f"    if (err != CborNoError) return false;")
    source_code.append(f"    return true;")
    source_code.append(f"}}")
    source_code.append("")


def main():
    parser = argparse.ArgumentParser(
        description="Generate CBOR encode/decode C code for structs from a C header."
    )
    parser.add_argument("header_file", help="Path to the C header file.")
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory to output generated C files (default: current directory).",
    )
    parser.add_argument(
        "--cpp-path",
        default="gcc",
        help="Path to the C preprocessor (e.g., 'gcc', 'clang').",
    )
    parser.add_argument(
        "--cpp-args",
        default="",
        help="Additional arguments to pass to the C preprocessor (e.g., '-I/path/to/includes').",
    )
    args = parser.parse_args()

    header_file_path = args.header_file
    output_dir = args.output_dir
    cpp_path = args.cpp_path
    cpp_args = args.cpp_args.split() if args.cpp_args else []

    if not os.path.exists(header_file_path):
        print(f"Error: Header file '{header_file_path}' not found.", file=sys.stderr)
        sys.exit(1)

    # Parse the C code using the preprocessor
    try:
        # pycparser.parse_file automatically runs the C preprocessor
        # and then parses the preprocessed output.
        file_ast = parse_file(
            header_file_path,
            use_cpp=True,
            cpp_path=cpp_path,
            cpp_args=["-E"] + cpp_args,
        )
    except c_parser.ParseError as e:
        print(f"Error parsing C header: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred during parsing: {e}", file=sys.stderr)
        sys.exit(1)

    all_struct_header_code = []
    all_struct_source_code = []

    # Collect all struct definitions first to handle forward declarations/nested structs
    struct_definitions = {}
    for ext in file_ast.ext:
        # Look for direct struct definitions
        if (
            isinstance(ext, c_ast.Decl)
            and isinstance(ext.type, c_ast.Struct)
            and ext.type.decls is not None
        ):
            if ext.type.name:  # Only named structs
                struct_definitions[ext.type.name] = ext.type
        # Look for typedef'd structs
        elif (
            isinstance(ext, c_ast.Typedef)
            and isinstance(ext.type, c_ast.TypeDecl)
            and isinstance(ext.type.type, c_ast.Struct)
            and ext.type.type.decls is not None
        ):
            if ext.type.type.name:  # Only named structs within typedef
                struct_definitions[ext.type.type.name] = ext.type.type
            elif ext.name:  # Anonymous struct with a typedef name
                # For anonymous structs with typedef, we use the typedef name as the struct name
                # This is a common pattern: `typedef struct { int x; } MyStruct;`
                # In this case, ext.type.type.name is None, but ext.name is 'MyStruct'
                # We need to create a dummy struct node with the typedef name for codegen
                # and copy its members.
                dummy_struct_node = copy.deepcopy(ext.type.type)
                dummy_struct_node.name = (
                    ext.name
                )  # Assign the typedef name as the struct name
                struct_definitions[ext.name] = dummy_struct_node

    # Now generate code for each defined struct
    for struct_name, struct_node in struct_definitions.items():
        header_part, source_part = generate_cbor_code_for_struct(struct_node, file_ast)
        all_struct_header_code.append(header_part)
        all_struct_source_code.append(source_part)

    # Generate cbor_generated.h
    header_output_path = os.path.join(output_dir, "cbor_generated.h")
    with open(header_output_path, "w") as f:
        f.write("#ifndef CBOR_GENERATED_H\n")
        f.write("#define CBOR_GENERATED_H\n\n")
        f.write("#include <stdbool.h>\n")
        f.write("#include <stdint.h>\n")
        f.write("#include <stddef.h>\n")
        f.write('#include "cbor.h"\n')
        f.write(
            f'#include "{os.path.basename(header_file_path)}"\n\n'
        )  # Include original header
        f.write("\n".join(all_struct_header_code))
        f.write("#endif // CBOR_GENERATED_H\n")
    print(f"Generated {header_output_path}")

    # Generate cbor_generated.c
    source_output_path = os.path.join(output_dir, "cbor_generated.c")
    with open(source_output_path, "w") as f:
        f.write('#include "cbor_generated.h"\n')
        f.write(
            f'#include "{os.path.basename(header_file_path)}"\n\n'
        )  # Include original header
        f.write("\n".join(all_struct_source_code))
    print(f"Generated {source_output_path}")


if __name__ == "__main__":
    main()
