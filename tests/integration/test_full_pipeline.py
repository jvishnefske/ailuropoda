import pytest
import subprocess
import os
import shutil
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

# Assuming the main script is in src/cbor_codegen.py
CBOR_CODEGEN_SCRIPT = Path(__file__).parent.parent.parent / "src" / "cbor_codegen.py"
TEST_HEADER_FILE = Path(__file__).parent / "simple_data.h"
TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"

@pytest.fixture(scope="module")
def setup_test_environment(tmp_path_factory):
    """
    Sets up a temporary directory for generated files and builds.
    """
    output_dir = tmp_path_factory.mktemp("cbor_generated_test")
    build_dir = output_dir / "build"
    build_dir.mkdir()

    # 1. Run cbor_codegen.py to generate cbor_generated.h/c
    print(f"Running cbor_codegen.py for {TEST_HEADER_FILE} into {output_dir}")
    try:
        subprocess.run(
            ["python", str(CBOR_CODEGEN_SCRIPT), str(TEST_HEADER_FILE), "--output-dir", str(output_dir)],
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        print(f"cbor_codegen.py failed with error: {e}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        pytest.fail(f"cbor_codegen.py failed: {e.stderr}")

    # 2. Render the C test harness template
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    c_test_harness_template = env.get_template("c_test_harness_simple_data.c.jinja")
    test_harness_c_file_name = "test_harness_simple_data.c"
    test_harness_executable_name = "cbor_test_simple_data"

    rendered_c_harness = c_test_harness_template.render()
    (output_dir / test_harness_c_file_name).write_text(rendered_c_harness)
    print(f"Generated C test harness: {output_dir / test_harness_c_file_name}")

    # 3. Render the CMakeLists.txt template, passing test harness info
    cmake_template = env.get_template("CMakeLists.txt.jinja")
    rendered_cmake = cmake_template.render(
        generated_library_name="cbor_generated", # This is hardcoded in the template
        generated_c_file_name="cbor_generated.c", # This is hardcoded in the template
        test_harness_c_file_name=test_harness_c_file_name,
        test_harness_executable_name=test_harness_executable_name
    )
    (output_dir / "CMakeLists.txt").write_text(rendered_cmake)
    print(f"Generated CMakeLists.txt: {output_dir / 'CMakeLists.txt'}")

    # Yield the paths for the test function
    yield output_dir, build_dir, test_harness_executable_name

    # Cleanup (optional, pytest-tmp_path handles it)
    # shutil.rmtree(output_dir)

def test_full_cbor_pipeline(setup_test_environment):
    output_dir, build_dir, test_executable_name = setup_test_environment

    # 4. Configure CMake
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

    # 5. Build the project
    print(f"Building project in {build_dir}...")
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

    # 6. Run the generated test executable
    test_executable_path = build_dir / test_executable_name
    if os.name == 'nt': # Windows executables typically have .exe extension
        test_executable_path = test_executable_path.with_suffix(".exe")

    print(f"Running test executable: {test_executable_path}")
    try:
        result = subprocess.run(
            [str(test_executable_path)],
            check=True,
            capture_output=True,
            text=True
        )
        print("Test executable output:")
        print(result.stdout)
        print(result.stderr)
        assert "All tests passed!" in result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Test executable failed with error: {e}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        pytest.fail(f"Test executable failed: {e.stderr}")
    except FileNotFoundError:
        pytest.fail(f"Test executable not found at {test_executable_path}. Check build process.")
