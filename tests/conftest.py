"""Shared pytest fixtures for ailuropoda tests."""
import pytest


@pytest.fixture(scope="module")
def cpp_info():
    """Fixture to provide cpp_path and cpp_args for pycparser."""
    return {"cpp_path": "cpp", "cpp_args": []}
