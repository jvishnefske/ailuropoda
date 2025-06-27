import pytest
from pathlib import Path
import subprocess
import shutil
import sys
import os # Import os for environment variables
from jinja2 import Environment, FileSystemLoader

# Define paths relative to the current test file
TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent.parent
SRC_DIR = PROJECT_ROOT / 'src'
TEMPLATES_DIR = PROJECT_ROOT / 'templates'

HEADER_FILE = TEST_DIR / 'simple_data.h'

# Setup Jinja2 environment for templates
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), trim_blocks=True, lstrip_blocks=True)

# Import cpp_info fixture from test_cbor_codegen for C preprocessor details
from tests.test_cbor_codegen import cpp_info

@pytest.fixture(scope="module") # Changed scope to module to build TinyCBOR once
def tinycbor_install_path(tmp_path_factory):
    """
    Fixture to clone, build, and install TinyCBOR and download doctest into a persistent temporary directory.
    This path will be used by CMake to find TinyCBOR and doctest.
    """
    build_path = tmp_path_factory.mktemp("tinycbor_build_env")
    tinycbor_repo_path = build_path / "tinycbor"
    tinycbor_build_path = build_path / "build"
    # Use a persistent install path for TinyCBOR and Doctest
    persistent_install_path = PROJECT_ROOT / 'build' / 'persistent_deps_install'
    persistent_install_path.mkdir(parents=True, exist_ok=True)

    # Clone TinyCBOR
    if not tinycbor_repo_path.exists():
        print(f"Cloning TinyCBOR into {tinycbor_repo_path}...")
        subprocess.run(
            ["git", "clone", "https://github.com/intel/tinycbor.git", str(tinycbor_repo_path)],
            check=True, capture_output=True
        )

    # Check if TinyCBOR is already installed in the persistent location
    if not (persistent_install_path / "include" / "tinycbor").exists() or \
       not (persistent_install_path / "lib").exists():
        print(f"\nPersistent TinyCBOR cache not found or incomplete. Building into {persistent_install_path}...")
        tinycbor_build_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["cmake", str(tinycbor_repo_path),
             "-DCMAKE_INSTALL_PREFIX=" + str(persistent_install_path),
             "-DCBOR_CONVERTER=OFF",
             "-DCMAKE_BUILD_TYPE=Release"],
            cwd=tinycbor_build_path,
            check=True, capture_output=True, text=True
        )
        subprocess.run(
            ["cmake", "--build", ".", "--target", "install"],
            cwd=tinycbor_build_path,
            check=True, capture_output=True, text=True
        )
        print(f"TinyCBOR installed to persistent cache at {persistent_install_path}")
    else:
        print(f"\nUsing persistent TinyCBOR cache from {persistent_install_path}")

    # Download doctest if not already present in the persistent cache
    doctest_include_dir = persistent_install_path / "include" / "doctest"
    if not doctest_include_dir.exists() or not (doctest_include_dir / "doctest.h").exists():
        print(f"Downloading doctest to {doctest_include_dir}...")
        doctest_temp_dir = build_path / "doctest_temp"
        doctest_temp_dir.mkdir(exist_ok=True)
        try:
            # Use curl or similar to download the raw header file
            # This is a simple way for header-only libs. For more complex, FetchContent in CMake is better.
            subprocess.run(
                ["curl", "-L", "https://github.com/doctest/doctest/releases/latest/download/doctest.h", "-o", str(doctest_temp_dir / "doctest.h")],
                check=True, capture_output=True, text=True
            )
            doctest_include_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(doctest_temp_dir / "doctest.h", doctest_include_dir / "doctest.h")
            print("doctest.h downloaded and cached.")
        except subprocess.CalledProcessError as e:
            print(f"Failed to download doctest: {e.stderr}")
            pytest.fail("Failed to download doctest")
        finally:
            shutil.rmtree(doctest_temp_dir)

    yield persistent_install_path

@pytest.fixture
def setup_test_environment(tmp_path, tinycbor_install_path, cpp_info):
    """
    Sets up a temporary directory for generated files and a build directory,
    and orchestrates the code generation and C test harness creation.
    """
    output_dir = tmp_path / "cbor_generated_output"
    output_dir.mkdir()
    # The main build directory will be at PROJECT_ROOT / 'build' / 'test_run_build_dir'

    # Get cpp_path and cpp_args from the fixture
    cpp_path, cpp_args = cpp_info
    generated_c_file_name = "cbor_generated.c"
    generated_h_file_name = "cbor_generated.h"
    generated_cmake_file_name = "CMakeLists.txt"
    test_harness_cpp_file_name = "test_harness.cpp"
    test_executable_name = f"cbor_test_{HEADER_FILE.stem}"
    generated_library_name = "cbor_generated"

    # Set up environment for the subprocess to find the 'ailuropoda' package
    env_for_subprocess = os.environ.copy()
    # Add SRC_DIR to PYTHONPATH so 'ailuropoda' can be imported as a module
    env_for_subprocess['PYTHONPATH'] = str(SRC_DIR) + os.pathsep + env_for_subprocess.get('PYTHONPATH', '')

    # 1. Run the code generator script as a subprocess
    print(f"Running src/ailuropoda/cbor_codegen.py for {HEADER_FILE} into {output_dir}")
    try:
        subprocess.run(
            [
                sys.executable, # Use the current Python interpreter
                "-m", "ailuropoda", # Run 'ailuropoda' as a module
                str(HEADER_FILE),
                "--output-dir", str(output_dir),
                "--cpp-path", cpp_path, # Pass cpp_path from fixture
                "--cpp-args", *cpp_args, # Pass cpp_args from fixture
                # Pass TinyCBOR include path to pycparser for parsing
                "-I" + str(tinycbor_install_path / "include")
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env_for_subprocess # Pass the modified environment
        )
    except subprocess.CalledProcessError as e:
        print(f"Code generation failed:\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}")
        pytest.fail("Code generation failed")

    assert (output_dir / generated_h_file_name).exists()
    assert (output_dir / generated_c_file_name).exists()
    assert (output_dir / generated_cmake_file_name).exists()

    # 2. Render the C++ test harness file from its template
    print(f"Rendering C++ test harness from template...")
    harness_template = env.get_template('c_test_harness_simple_data.cpp.jinja') # Correct template name
    # Use Path.relative_to with walk_up=True to handle paths outside the output_dir
    rendered_harness = harness_template.render(
        input_header_path=HEADER_FILE.relative_to(output_dir, walk_up=True)
    )
    (output_dir / test_harness_cpp_file_name).write_text(rendered_harness)
    print(f"Generated C++ test harness: {output_dir / test_harness_cpp_file_name}")

    # 3. Re-render CMakeLists.txt to include the test harness executable
    print(f"Re-rendering CMakeLists.txt to include test harness...")
    cmake_template = env.get_template('CMakeLists.txt.jinja')
    rendered_cmake = cmake_template.render(
        generated_library_name=generated_library_name,
        generated_c_file_name=generated_c_file_name,
        test_harness_c_file_name=test_harness_cpp_file_name, # Pass the .cpp file name
        test_harness_executable_name=test_executable_name
    )
    (output_dir / generated_cmake_file_name).write_text(rendered_cmake)

    # The main build directory for the entire project
    main_build_dir = tmp_path / "main_project_build"
    main_build_dir.mkdir()

    yield output_dir, main_build_dir, test_executable_name, tinycbor_install_path

def test_full_cbor_pipeline(setup_test_environment):
    output_dir, main_build_dir, test_executable_name, tinycbor_install_path = setup_test_environment

    # 4. Configure the main CMake project
    print(f"Configuring main CMake project in {main_build_dir}...")
    cmake_configure_args = [
        "cmake",
        str(PROJECT_ROOT), # Source directory is project root
        f"-B{main_build_dir.name}", # Binary directory relative to cwd
        f"-DCMAKE_PREFIX_PATH={tinycbor_install_path}", # Point CMake to TinyCBOR and Doctest install
        f"-DGENERATED_CODE_DIR={output_dir}", # Pass the path to the generated code
        "-DCMAKE_BUILD_TYPE=Release"
    ]
    result = subprocess.run(cmake_configure_args, cwd=main_build_dir, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"CMake configure failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        pytest.fail("CMake configure failed")

    print(f"Building project in {main_build_dir}...")
    # 5. Build the project
    result = subprocess.run(
        ["cmake", "--build", "."],
        cwd=main_build_dir, # Build from the main build directory
        check=False,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"CMake build failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        pytest.fail("CMake build failed")

    # 6. Run the generated test executable
    # The executable will be in the subdirectory created by add_subdirectory
    test_executable_path = main_build_dir / "generated_cbor_build" / test_executable_name
    if not test_executable_path.exists():
        # On some systems (e.g., Windows), executables might have .exe extension
        test_executable_path = main_build_dir / "generated_cbor_build" / (test_executable_name + ".exe")
    
    if not test_executable_path.exists():
        pytest.fail(f"Test executable not found at {test_executable_path} after build.")

    print(f"Running test executable: {test_executable_path}")
    result = subprocess.run(
        [str(test_executable_path)],
        check=False,
        capture_output=True,
        text=True
    )

    # Assert that the doctest C++ test harness exited successfully (return code 0)
    if result.returncode != 0:
        print(f"Doctest C++ test harness failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        pytest.fail(f"Doctest C++ test harness exited with non-zero status {result.returncode}")
    
    print(f"Doctest C++ test harness output:\n{result.stdout}")
    # Doctest output format: [doctest] test cases: X | Y passed | Z failed
    assert "[doctest] test cases:" in result.stdout
    assert "| 0 failed" in result.stdout # Ensure no tests failed
    print("Full pipeline test completed successfully.")
