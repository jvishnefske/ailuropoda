import pytest
from pathlib import Path
import subprocess
import shutil
import sys
from jinja2 import Environment, FileSystemLoader

# Define paths relative to the current test file
TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent.parent
SRC_DIR = PROJECT_ROOT / 'src'
TEMPLATES_DIR = PROJECT_ROOT / 'templates'

HEADER_FILE = TEST_DIR / 'simple_data.h'

# Setup Jinja2 environment for templates
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), trim_blocks=True, lstrip_blocks=True)

@pytest.fixture(scope="module") # Changed scope to module to build TinyCBOR once
def tinycbor_install_path(tmp_path_factory):
    """
    Fixture to clone, build, and install TinyCBOR into a temporary directory.
    This path will be used by CMake to find TinyCBOR.
    """
    build_path = tmp_path_factory.mktemp("tinycbor_build_env")
    tinycbor_repo_path = build_path / "tinycbor"
    tinycbor_build_path = build_path / "build"
    install_path = build_path / "install"

    # Clone TinyCBOR
    if not tinycbor_repo_path.exists():
        print(f"Cloning TinyCBOR into {tinycbor_repo_path}...")
        subprocess.run(
            ["git", "clone", "https://github.com/intel/tinycbor.git", str(tinycbor_repo_path)],
            check=True, capture_output=True
        )

    # Configure and build TinyCBOR
    tinycbor_build_path.mkdir(parents=True, exist_ok=True) # Use Path.mkdir
    print(f"Configuring and building TinyCBOR in {tinycbor_build_path}...")
    subprocess.run(
        ["cmake", str(tinycbor_repo_path),
         "-DCMAKE_INSTALL_PREFIX=" + str(install_path),
         "-DCBOR_CONVERTER=OFF", # We don't need the converter for this test
         "-DCMAKE_BUILD_TYPE=Release"],
        cwd=tinycbor_build_path,
        check=True, capture_output=True
    )
    subprocess.run(
        ["cmake", "--build", ".", "--target", "install"],
        cwd=tinycbor_build_path,
        check=True, capture_output=True
    )
    print(f"TinyCBOR installed to {install_path}")
    yield install_path

@pytest.fixture
def setup_test_environment(tmp_path, tinycbor_install_path):
    """
    Sets up a temporary directory for generated files and a build directory,
    and orchestrates the code generation and C test harness creation.
    """
    output_dir = tmp_path / "cbor_generated_output"
    build_dir = output_dir / "build"
    output_dir.mkdir()
    build_dir.mkdir()

    generated_c_file_name = "cbor_generated.c"
    generated_h_file_name = "cbor_generated.h"
    generated_cmake_file_name = "CMakeLists.txt"
    test_harness_c_file_name = "test_harness.c"
    test_executable_name = f"cbor_test_{HEADER_FILE.stem}"
    generated_library_name = "cbor_generated"

    # 1. Run the code generator script as a subprocess
    print(f"Running src/ailuropoda/cbor_codegen.py for {HEADER_FILE} into {output_dir}")
    try:
        subprocess.run(
            [
                sys.executable, # Use the current Python interpreter
                str(SRC_DIR / 'ailuropoda' / 'cbor_codegen.py'), # Corrected path
                str(HEADER_FILE),
                "--output-dir", str(output_dir),
                # Pass TinyCBOR include path to pycparser for parsing
                "--cpp-args=-I" + str(tinycbor_install_path / "include")
            ],
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        print(f"Code generation failed:\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}")
        pytest.fail("Code generation failed")

    assert (output_dir / generated_h_file_name).exists()
    assert (output_dir / generated_c_file_name).exists()
    assert (output_dir / generated_cmake_file_name).exists()

    # 2. Render the C test harness file from its template
    print(f"Rendering C test harness from template...")
    harness_template = env.get_template('c_test_harness_simple_data.c.jinja')
    rendered_harness = harness_template.render(
        input_header_path=HEADER_FILE.relative_to(output_dir) # Use Path.relative_to
    )
    (output_dir / test_harness_c_file_name).write_text(rendered_harness)
    print(f"Generated C test harness: {output_dir / test_harness_c_file_name}")

    # 3. Re-render CMakeLists.txt to include the test harness executable
    print(f"Re-rendering CMakeLists.txt to include test harness...")
    cmake_template = env.get_template('CMakeLists.txt.jinja')
    rendered_cmake = cmake_template.render(
        generated_library_name=generated_library_name,
        generated_c_file_name=generated_c_file_name,
        test_harness_c_file_name=test_harness_c_file_name,
        test_harness_executable_name=test_executable_name
    )
    (output_dir / generated_cmake_file_name).write_text(rendered_cmake)

    yield output_dir, build_dir, test_executable_name, tinycbor_install_path

def test_full_cbor_pipeline(setup_test_environment): # Removed 'subprocess' from arguments
    output_dir, build_dir, test_executable_name, tinycbor_install_path = setup_test_environment

    # 4. Configure CMake
    print(f"Configuring CMake in {build_dir}...")
    cmake_configure_args = [
        "cmake",
        str(output_dir),
        f"-DCMAKE_PREFIX_PATH={tinycbor_install_path}", # Point CMake to TinyCBOR install
        "-DCMAKE_BUILD_TYPE=Release" # Ensure release build for speed/size
    ]
    result = subprocess.run(cmake_configure_args, cwd=build_dir, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"CMake configure failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        pytest.fail("CMake configure failed")

    print(f"Building project in {build_dir}...")
    # 5. Build the project
    result = subprocess.run(
        ["cmake", "--build", "."],
        cwd=build_dir,
        check=False,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"CMake build failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        pytest.fail("CMake build failed")

    # 6. Run the generated test executable
    test_executable_path = build_dir / test_executable_name
    if not test_executable_path.exists():
        # On some systems (e.g., Windows), executables might have .exe extension
        test_executable_path = build_dir / (test_executable_name + ".exe")
    
    if not test_executable_path.exists():
        pytest.fail(f"Test executable not found at {test_executable_path} after build.")

    print(f"Running test executable: {test_executable_path}")
    result = subprocess.run(
        [str(test_executable_path)],
        check=False,
        capture_output=True,
        text=True
    )

    # Assert that the C test harness exited successfully (return code 0)
    if result.returncode != 0:
        print(f"C test harness failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        pytest.fail(f"C test harness exited with non-zero status {result.returncode}")
    
    print(f"C test harness output:\n{result.stdout}")
    assert "All tests passed successfully." in result.stdout
    print("Full pipeline test completed successfully.")
