import pytest
from pathlib import Path
import subprocess
import shutil
import os
import sys

# Add the src directory to the Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from cbor_codegen import generate_cbor_code

# Define paths relative to the current test file
TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent.parent
HEADER_FILE = TEST_DIR / 'simple_data.h'
TEST_HARNESS_TEMPLATE = TEST_DIR / 'test_harness_template.c.jinja'

@pytest.fixture
def setup_test_environment(tmp_path):
    """
    Sets up a temporary directory for generated files and a build directory.
    """
    output_dir = tmp_path / "cbor_generated_test"
    build_dir = output_dir / "build"
    output_dir.mkdir()
    build_dir.mkdir()

    test_executable_name = f"cbor_test_{HEADER_FILE.stem}"
    
    # 1. Run the code generator
    print(f"Running cbor_codegen.py for {HEADER_FILE} into {output_dir}")
    success = generate_cbor_code(HEADER_FILE, output_dir, test_harness_name=test_executable_name)
    assert success, "Code generation failed"

    # 2. Generate the C test harness file from its template
    # This part is usually handled by the main script or a separate test setup.
    # For this integration test, we'll manually create a dummy test harness C file
    # that includes the generated header and has a main function.
    # In a real scenario, this would be a more complex test application.
    test_harness_c_content = f"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "{output_dir.name}/cbor_generated.h" // Include the generated header
#include "{HEADER_FILE.name}" // Include the original header with struct definitions
#include "tinycbor/cbor.h" // Include tinycbor for direct usage if needed

// Dummy main function for the test harness
int main() {{
    printf("Test harness for {HEADER_FILE.name} running.\\n");

    // Example usage of generated functions (simplified)
    struct SimpleData test_data = {{
        .id = 123,
        .name = "TestName",
        .is_active = true,
        .temperature = 25.5f,
        .flags = {{1, 2, 3, 4}}
    }};

    uint8_t buffer[256];
    CborEncoder encoder;
    cbor_encoder_init(&encoder, buffer, sizeof(buffer), 0);

    if (encode_SimpleData(&test_data, &encoder)) {{
        printf("SimpleData encoded successfully.\\n");
    }} else {{
        fprintf(stderr, "Failed to encode SimpleData.\\n");
        return 1;
    }}

    size_t encoded_len = cbor_encoder_get_buffer_size(&encoder, buffer);
    printf("Encoded size: %zu bytes\\n", encoded_len);

    // Decode back
    struct SimpleData decoded_data;
    // For char* members, ensure they are allocated before decoding
    // For SimpleData, 'name' is a char array, so no malloc needed.
    // For NestedData, 'description' is char*, so it would need allocation.
    // This test only uses SimpleData, so it's fine.

    CborParser parser;
    CborValue it;
    CborError err = cbor_parser_init(buffer, encoded_len, 0, &parser, &it);
    if (err != CborNoError) {{
        fprintf(stderr, "Failed to initialize CBOR parser: %s\\n", cbor_error_string(err));
        return 1;
    }}

    if (decode_SimpleData(&decoded_data, &it)) {{
        printf("SimpleData decoded successfully.\\n");
        printf("Decoded ID: %d\\n", decoded_data.id);
        printf("Decoded Name: %s\\n", decoded_data.name);
        printf("Decoded Is Active: %s\\n", decoded_data.is_active ? "true" : "false");
        printf("Decoded Temperature: %f\\n", decoded_data.temperature);
        printf("Decoded Flags: [%d, %d, %d, %d]\\n", decoded_data.flags[0], decoded_data.flags[1], decoded_data.flags[2], decoded_data.flags[3]);

        // Basic assertions
        if (decoded_data.id != test_data.id ||
            strcmp(decoded_data.name, test_data.name) != 0 ||
            decoded_data.is_active != test_data.is_active ||
            decoded_data.temperature != test_data.temperature ||
            memcmp(decoded_data.flags, test_data.flags, sizeof(test_data.flags)) != 0)
        {{
            fprintf(stderr, "Decoded data does not match original data!\\n");
            return 1;
        }}

    }} else {{
        fprintf(stderr, "Failed to decode SimpleData.\\n");
        return 1;
    }}

    // Test NestedData (requires manual allocation for char* description)
    struct NestedData original_nested = {{
        .inner_data = {{
            .id = 456,
            .name = "NestedItem",
            .is_active = false,
            .temperature = 99.9f,
            .flags = {{5, 6, 7, 8}}
        }},
        .description = (char*)malloc(256), // Allocate memory for description
        .value = 789
    }};
    if (!original_nested.description) {{
        fprintf(stderr, "Failed to allocate memory for description.\\n");
        return 1;
    }}
    strcpy(original_nested.description, "This is a nested description.");

    uint8_t nested_buffer[512];
    CborEncoder nested_encoder;
    cbor_encoder_init(&nested_encoder, nested_buffer, sizeof(nested_buffer), 0);

    if (encode_NestedData(&original_nested, &nested_encoder)) {{
        printf("NestedData encoded successfully.\\n");
    }} else {{
        fprintf(stderr, "Failed to encode NestedData.\\n");
        free(original_nested.description);
        return 1;
    }}

    size_t nested_encoded_len = cbor_encoder_get_buffer_size(&nested_encoder, nested_buffer);
    printf("Nested Encoded size: %zu bytes\\n", nested_encoded_len);

    struct NestedData decoded_nested;
    decoded_nested.description = (char*)malloc(256); // Allocate memory for description
    if (!decoded_nested.description) {{
        fprintf(stderr, "Failed to allocate memory for decoded description.\\n");
        free(original_nested.description);
        return 1;
    }}

    CborParser nested_parser;
    CborValue nested_it;
    err = cbor_parser_init(nested_buffer, nested_encoded_len, 0, &nested_parser, &nested_it);
    if (err != CborNoError) {{
        fprintf(stderr, "Failed to initialize nested CBOR parser: %s\\n", cbor_error_string(err));
        free(original_nested.description);
        free(decoded_nested.description);
        return 1;
    }}

    if (decode_NestedData(&decoded_nested, &nested_it)) {{
        printf("NestedData decoded successfully.\\n");
        printf("Decoded Nested ID: %d\\n", decoded_nested.inner_data.id);
        printf("Decoded Nested Name: %s\\n", decoded_nested.inner_data.name);
        printf("Decoded Nested Description: %s\\n", decoded_nested.description);
        printf("Decoded Nested Value: %d\\n", decoded_nested.value);

        // Basic assertions for nested data
        if (decoded_nested.inner_data.id != original_nested.inner_data.id ||
            strcmp(decoded_nested.inner_data.name, original_nested.inner_data.name) != 0 ||
            strcmp(decoded_nested.description, original_nested.description) != 0 ||
            decoded_nested.value != original_nested.value)
        {{
            fprintf(stderr, "Decoded nested data does not match original data!\\n");
            return 1;
        }}

    }} else {{
        fprintf(stderr, "Failed to decode NestedData.\\n");
        return 1;
    }}

    free(original_nested.description);
    free(decoded_nested.description);

    printf("All tests passed successfully.\\n");
    return 0;
}}
    """
    test_harness_c_file = output_dir / f"test_harness_{HEADER_FILE.stem}.c"
    test_harness_c_file.write_text(test_harness_c_content)
    print(f"Generated C test harness: {test_harness_c_file}")

    yield output_dir, build_dir, test_executable_name

    # Teardown: Clean up the temporary directory
    # shutil.rmtree(tmp_path) # pytest's tmp_path fixture handles cleanup

def test_full_cbor_pipeline(setup_test_environment):
    output_dir, build_dir, test_executable_name = setup_test_environment

    # 3. Configure CMake
    print(f"Configuring CMake in {build_dir}...")
    try:
        subprocess.run(
            ["cmake", "-S", str(output_dir), "-B", str(build_dir)],
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        print(f"CMake configure failed with error: {e}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        pytest.fail(f"CMake configure failed: {e.stderr}")

    print(f"Building project in {build_dir}...")
    # 4. Build the project
    try:
        subprocess.run(
            ["cmake", "--build", str(build_dir)],
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        print(f"CMake build failed with error: {e}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        pytest.fail(f"CMake build failed: {e.stderr}")

    # 5. Run the generated test executable
    print(f"Running test executable: {build_dir / test_executable_name}")
    try:
        result = subprocess.run(
            [str(build_dir / test_executable_name)],
            check=True,
            capture_output=True,
            text=True
        )
        print("Test executable output:")
        print(result.stdout)
        if result.stderr:
            print("Test executable stderr:")
            print(result.stderr)
    except subprocess.CalledProcessError as e:
        print(f"Test executable failed with error: {e}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        pytest.fail(f"Test executable failed: {e.stderr}")

    assert "All tests passed successfully." in result.stdout
    print("Full pipeline test completed successfully.")
