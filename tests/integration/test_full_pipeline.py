import pytest
from pathlib import Path
import subprocess
import shutil
import sys
import os  # Import os for environment variables
# Define paths relative to the current test file
TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent.parent

# The name of the test executable defined in tests/integration/CMakeLists.txt
TEST_EXECUTABLE_NAME = "ailuropoda_simple_data_integration_test"


@pytest.fixture(scope="module")  # Changed scope to module to build TinyCBOR once
def tinycbor_install_path(tmp_path_factory):
    """
    Fixture to clone, build, and install TinyCBOR and download doctest into a persistent directory.
    This path will be used by CMake to find TinyCBOR and doctest.
    """
    # Define persistent paths for source and installation
    persistent_install_path = PROJECT_ROOT / "build" / "persistent_deps_install"
    persistent_tinycbor_repo_path = PROJECT_ROOT / "build" / "persistent_deps_src" / "tinycbor"
    persistent_doctest_include_dir = persistent_install_path / "include" / "doctest"

    # Ensure parent directories for persistent caches exist
    persistent_install_path.mkdir(parents=True, exist_ok=True)
    # persistent_tinycbor_repo_path's parent will be created by git clone or its own mkdir if needed

    # --- Handle TinyCBOR ---
    # Check if TinyCBOR is already installed in the persistent location
    tinycbor_installed_check = (persistent_install_path / "include" / "tinycbor").exists() and (
        persistent_install_path / "lib"
    ).exists()

    if not tinycbor_installed_check:
        print(
            f"\nPersistent TinyCBOR cache not found or incomplete. Attempting to build and install into {persistent_install_path}..."
        )

        # 1. Ensure TinyCBOR source is available (clone if not present)
        if not (persistent_tinycbor_repo_path / ".git").exists():
            print(f"Cloning TinyCBOR into {persistent_tinycbor_repo_path}...")
            try:
                # Ensure parent directory for the repo exists before cloning
                persistent_tinycbor_repo_path.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    [
                        "git",
                        "clone",
                        "https://github.com/intel/tinycbor.git",
                        str(persistent_tinycbor_repo_path),
                    ],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as e:
                print(f"Failed to clone TinyCBOR:\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}")
                pytest.fail("Failed to clone TinyCBOR")
        else:
            print(f"Using existing TinyCBOR source from {persistent_tinycbor_repo_path}")

        # 2. Build and install TinyCBOR from the persistent source
        tinycbor_build_path = tmp_path_factory.mktemp("tinycbor_build")
        tinycbor_build_path.mkdir(parents=True, exist_ok=True)

        try:
            subprocess.run(
                [
                    "cmake",
                    str(persistent_tinycbor_repo_path),  # Source is the persistent repo
                    "-DCMAKE_INSTALL_PREFIX=" + str(persistent_install_path),
                    "-DCBOR_CONVERTER=OFF",
                    "-DCMAKE_BUILD_TYPE=Release",
                ],
                cwd=tinycbor_build_path,  # Build in the temporary build dir
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["cmake", "--build", ".", "--target", "install"],
                cwd=tinycbor_build_path,
                check=True,
                capture_output=True,
                text=True,
            )
            print(f"TinyCBOR installed to persistent cache at {persistent_install_path}")
        except subprocess.CalledProcessError as e:
            print(f"TinyCBOR build/install failed:\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}")
            pytest.fail("TinyCBOR build/install failed")
    else:
        print(f"\nUsing persistent TinyCBOR cache from {persistent_install_path}")

    # --- Handle doctest ---
    # Download doctest if not already present in the persistent cache
    if not persistent_doctest_include_dir.exists() or not (persistent_doctest_include_dir / "doctest.h").exists():
        print(f"Downloading doctest to {persistent_doctest_include_dir}...")
        # Use a temporary directory for downloading doctest
        doctest_temp_dir = tmp_path_factory.mktemp("doctest_temp")
        try:
            subprocess.run(
                [
                    "curl",
                    "-L",
                    "https://github.com/doctest/doctest/releases/latest/download/doctest.h",
                    "-o",
                    str(doctest_temp_dir / "doctest.h"),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            persistent_doctest_include_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(
                doctest_temp_dir / "doctest.h",
                persistent_doctest_include_dir / "doctest.h",
            )
            print("doctest.h downloaded and cached.")
        except subprocess.CalledProcessError as e:
            print(f"Failed to download doctest: {e.stderr}")
            pytest.fail("Failed to download doctest")
        finally:
            # Clean up the temporary download directory
            if doctest_temp_dir.exists():
                shutil.rmtree(doctest_temp_dir)
    else:
        print(f"Using persistent doctest cache from {persistent_doctest_include_dir}")

    yield persistent_install_path


@pytest.fixture
def setup_test_environment(tmp_path, tinycbor_install_path):
    """
    Sets up a temporary build directory for the example CMake project.
    """
    # The source directory for the example CMake project is TEST_DIR itself.
    example_project_source_dir = TEST_DIR
    main_build_dir = tmp_path / "integration_example_build"
    main_build_dir.mkdir()

    # No Python-based code generation or template rendering is done here.
    # The CMakeLists.txt within example_project_source_dir will handle that.

    yield example_project_source_dir, main_build_dir, TEST_EXECUTABLE_NAME, tinycbor_install_path


def test_full_cbor_pipeline(setup_test_environment):
    example_project_source_dir, main_build_dir, test_executable_name, tinycbor_install_path = setup_test_environment

    print(f"Configuring example CMake project in {main_build_dir} from source {example_project_source_dir}...")
    cmake_configure_args = [
        "cmake",
        str(example_project_source_dir),  # Source directory is the integration test directory
        "-B.",  # Binary directory is the current working directory (main_build_dir)
        f"-DCMAKE_PREFIX_PATH={tinycbor_install_path}",  # Point CMake to TinyCBOR and Doctest install
        # No -DGENERATED_CODE_DIR needed; the example CMakeLists.txt defines its own generated output.
        "-DCMAKE_BUILD_TYPE=Release",
    ]
    result = subprocess.run(
        cmake_configure_args,
        cwd=main_build_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"CMake configure failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        pytest.fail("CMake configure failed")

    print(f"Building example project in {main_build_dir}...")
    result = subprocess.run(
        ["cmake", "--build", "."],
        cwd=main_build_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"CMake build failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        pytest.fail("CMake build failed")

    # 6. Run the generated test executable
    # The executable is now directly in the build directory of the example project
    test_executable_path = main_build_dir / test_executable_name
    if not test_executable_path.exists():
        # On some systems (e.g., Windows), executables might have .exe extension
        test_executable_path = main_build_dir / (test_executable_name + ".exe")

    if not test_executable_path.exists():
        pytest.fail(f"Test executable not found at {test_executable_path} after build.")

    print(f"Running test executable: {test_executable_path}")
    result = subprocess.run([str(test_executable_path)], check=False, capture_output=True, text=True)

    # Assert that the doctest C++ test harness exited successfully (return code 0)
    if result.returncode != 0:
        print(f"Doctest C++ test harness failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        pytest.fail(f"Doctest C++ test harness exited with non-zero status {result.returncode}")

    print(f"Doctest C++ test harness output:\n{result.stdout}")
    assert "[doctest] test cases:" in result.stdout
    assert "| 0 failed" in result.stdout
    print("Full pipeline test completed successfully.")
