"""
Contract-driven test suite for ImageBuilder component.
Tests verify behavior at boundaries with mocked dependencies.
"""

import pytest
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open, call
from datetime import datetime
from typing import Any, Dict, List
import subprocess

# Import the component under test
# Adjust import based on actual module structure
try:
    from src.baton.image import ImageBuilder, ImageInfo, IMAGES_FILE
except ImportError:
    try:
        from src_baton_image import ImageBuilder, ImageInfo, IMAGES_FILE
    except ImportError:
        # Fallback for testing - define minimal types
        class ImageInfo:
            def __init__(self, node_name: str, tag: str, built_at: str, digest: str):
                self.node_name = node_name
                self.tag = tag
                self.built_at = built_at
                self.digest = digest
        
        IMAGES_FILE = "images.json"
        
        # Define a minimal ImageBuilder for testing if import fails
        class ImageBuilder:
            def __init__(self, project_dir, circuit_name):
                self._project_dir = Path(project_dir)
                self._circuit_name = circuit_name


# Custom exceptions expected by contract
class FileSystemError(Exception):
    """Error during filesystem operations"""
    pass


class DockerBuildFailure(Exception):
    """Error during Docker build"""
    pass


class DockerPushFailure(Exception):
    """Error during Docker push"""
    pass


class FileReadError(Exception):
    """Error reading file"""
    pass


class FileWriteError(Exception):
    """Error writing file"""
    pass


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
def temp_project_dir(tmp_path):
    """Create a temporary project directory structure"""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    baton_dir = project_dir / ".baton"
    baton_dir.mkdir()
    dockerfiles_dir = baton_dir / "dockerfiles"
    dockerfiles_dir.mkdir()
    return project_dir


@pytest.fixture
def image_builder(temp_project_dir):
    """Create an ImageBuilder instance with temp directory"""
    return ImageBuilder(str(temp_project_dir), "test_circuit")


@pytest.fixture
def sample_image_info():
    """Create a sample ImageInfo object"""
    return ImageInfo(
        node_name="test_node",
        tag="test_circuit-test_node:latest",
        built_at="2024-01-01T00:00:00",
        digest="sha256:abcdef123456"
    )


@pytest.fixture
def mock_docker_client():
    """Mock Docker client for testing"""
    client = MagicMock()
    client.images.build.return_value = (MagicMock(id="sha256:abcdef"), [])
    return client


# ==============================================================================
# __init__ TESTS
# ==============================================================================

def test_init_happy_path_with_str():
    """Initialize ImageBuilder with string project_dir and circuit_name"""
    project_dir = "/tmp/test_project"
    circuit_name = "test_circuit"
    
    builder = ImageBuilder(project_dir, circuit_name)
    
    assert builder._project_dir == Path(project_dir), "project_dir should be converted to Path"
    assert builder._circuit_name == circuit_name, "circuit_name should be stored as-is"
    assert isinstance(builder._project_dir, Path), "_project_dir should be Path instance"


def test_init_happy_path_with_path():
    """Initialize ImageBuilder with Path object for project_dir"""
    project_dir = Path("/tmp/test_project")
    circuit_name = "test_circuit"
    
    builder = ImageBuilder(project_dir, circuit_name)
    
    assert builder._project_dir == project_dir, "Path object should be preserved"
    assert builder._circuit_name == circuit_name, "circuit_name should be stored"
    assert isinstance(builder._project_dir, Path), "_project_dir should be Path instance"


def test_init_edge_case_relative_path():
    """Initialize ImageBuilder with relative path"""
    project_dir = "./relative/path"
    circuit_name = "test_circuit"
    
    builder = ImageBuilder(project_dir, circuit_name)
    
    assert isinstance(builder._project_dir, Path), "_project_dir should be Path instance"
    assert builder._circuit_name == circuit_name, "circuit_name should be stored"


# ==============================================================================
# detect_runtime TESTS
# ==============================================================================

def test_detect_runtime_happy_path_node(temp_project_dir):
    """Detect Node.js runtime when package.json exists"""
    service_dir = temp_project_dir / "node_service"
    service_dir.mkdir()
    package_json = service_dir / "package.json"
    package_json.write_text('{"name": "test"}')
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    result = builder.detect_runtime(service_dir)
    
    assert result == "node", "Should detect Node.js runtime when package.json exists"


def test_detect_runtime_happy_path_python(temp_project_dir):
    """Detect Python runtime when package.json does not exist"""
    service_dir = temp_project_dir / "python_service"
    service_dir.mkdir()
    # No package.json created
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    result = builder.detect_runtime(service_dir)
    
    assert result == "python", "Should detect Python runtime when package.json doesn't exist"


def test_detect_runtime_edge_case_empty_dir(temp_project_dir):
    """Detect runtime for empty directory defaults to Python"""
    service_dir = temp_project_dir / "empty_service"
    service_dir.mkdir()
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    result = builder.detect_runtime(service_dir)
    
    assert result == "python", "Should default to Python for empty directory"


# ==============================================================================
# generate_dockerfile TESTS
# ==============================================================================

def test_generate_dockerfile_happy_path_python(temp_project_dir):
    """Generate Dockerfile for Python service"""
    service_dir = temp_project_dir / "python_service"
    service_dir.mkdir()
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    with patch.object(builder, 'detect_runtime', return_value='python'):
        result = builder.generate_dockerfile("python_node", service_dir)
    
    assert result.name == "Dockerfile.python_node", "Dockerfile should have correct name"
    assert result.exists(), "Dockerfile should be created"
    
    dockerfile_content = result.read_text()
    assert "python:3.12-slim" in dockerfile_content, "Should use Python 3.12 slim image"
    assert "EXPOSE 8080" in dockerfile_content, "Should expose port 8080"
    assert "WORKDIR /app" in dockerfile_content, "Should set WORKDIR to /app"
    assert "PORT=8080" in dockerfile_content or "PORT 8080" in dockerfile_content, "Should set PORT env"


def test_generate_dockerfile_happy_path_node(temp_project_dir):
    """Generate Dockerfile for Node.js service"""
    service_dir = temp_project_dir / "node_service"
    service_dir.mkdir()
    package_json = service_dir / "package.json"
    package_json.write_text('{"name": "test"}')
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    with patch.object(builder, 'detect_runtime', return_value='node'):
        result = builder.generate_dockerfile("node_service", service_dir)
    
    assert result.name == "Dockerfile.node_service", "Dockerfile should have correct name"
    assert result.exists(), "Dockerfile should be created"
    
    dockerfile_content = result.read_text()
    assert "node:20-slim" in dockerfile_content, "Should use Node 20 slim image"
    assert "EXPOSE 8080" in dockerfile_content, "Should expose port 8080"
    assert "WORKDIR /app" in dockerfile_content, "Should set WORKDIR to /app"
    assert "PORT=8080" in dockerfile_content or "PORT 8080" in dockerfile_content, "Should set PORT env"


def test_generate_dockerfile_error_filesystem(temp_project_dir):
    """Generate Dockerfile fails when unable to create directory"""
    service_dir = temp_project_dir / "service"
    service_dir.mkdir()
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    dockerfiles_dir = temp_project_dir / ".baton" / "dockerfiles"
    
    with patch.object(Path, 'mkdir', side_effect=PermissionError("No permission")):
        with pytest.raises((FileSystemError, PermissionError, OSError)):
            builder.generate_dockerfile("test_node", service_dir)


def test_generate_dockerfile_error_json_decode(temp_project_dir):
    """Generate Dockerfile fails when package.json contains invalid JSON"""
    service_dir = temp_project_dir / "node_service"
    service_dir.mkdir()
    package_json = service_dir / "package.json"
    package_json.write_text('{"invalid json}')  # Malformed JSON
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    # The detect_runtime or node entry detection might raise JSONDecodeError
    with patch.object(builder, '_detect_node_entry', side_effect=json.JSONDecodeError("Invalid", "", 0)):
        with pytest.raises((json.JSONDecodeError, Exception)):
            builder.generate_dockerfile("test_node", service_dir)


# ==============================================================================
# build TESTS
# ==============================================================================

def test_build_happy_path(temp_project_dir, mock_docker_client):
    """Build Docker image successfully"""
    service_dir = temp_project_dir / "service"
    service_dir.mkdir()
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    tag = "test_circuit-test_node:latest"
    
    mock_subprocess = MagicMock()
    mock_subprocess.returncode = 0
    mock_subprocess.stdout = "Successfully built"
    
    with patch('subprocess.run', return_value=mock_subprocess):
        with patch.object(builder, 'generate_dockerfile', return_value=temp_project_dir / ".baton" / "dockerfiles" / "Dockerfile.test_node"):
            with patch.object(builder, '_save_image_info'):
                with patch('subprocess.check_output', return_value=b'sha256:abcdef123456\n'):
                    result = builder.build("test_node", service_dir, tag)
    
    assert result.node_name == "test_node", "ImageInfo should have correct node_name"
    assert result.tag == tag, "ImageInfo should have correct tag"
    assert result.digest is not None, "ImageInfo should have digest"
    assert isinstance(result.built_at, str), "ImageInfo should have built_at timestamp"


def test_build_error_docker_build_failure(temp_project_dir):
    """Build fails when Docker build command returns non-zero"""
    service_dir = temp_project_dir / "service"
    service_dir.mkdir()
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    mock_subprocess = MagicMock()
    mock_subprocess.returncode = 1
    mock_subprocess.stderr = "Build failed"
    
    with patch('subprocess.run', return_value=mock_subprocess):
        with patch.object(builder, 'generate_dockerfile', return_value=temp_project_dir / ".baton" / "dockerfiles" / "Dockerfile.test_node"):
            with pytest.raises((DockerBuildFailure, subprocess.CalledProcessError, Exception)):
                builder.build("test_node", service_dir, "test:latest")


def test_build_error_filesystem(temp_project_dir):
    """Build fails when unable to save image info"""
    service_dir = temp_project_dir / "service"
    service_dir.mkdir()
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    mock_subprocess = MagicMock()
    mock_subprocess.returncode = 0
    
    with patch('subprocess.run', return_value=mock_subprocess):
        with patch.object(builder, 'generate_dockerfile', return_value=temp_project_dir / ".baton" / "dockerfiles" / "Dockerfile.test_node"):
            with patch.object(builder, '_save_image_info', side_effect=FileSystemError("Cannot write")):
                with patch('subprocess.check_output', return_value=b'sha256:abcdef\n'):
                    with pytest.raises((FileSystemError, Exception)):
                        builder.build("test_node", service_dir, "test:latest")


# ==============================================================================
# push TESTS
# ==============================================================================

def test_push_happy_path(temp_project_dir):
    """Push Docker image successfully"""
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    tag = "registry.example.com/test:latest"
    
    mock_subprocess = MagicMock()
    mock_subprocess.returncode = 0
    mock_subprocess.stdout = "Pushed"
    
    with patch('subprocess.run', return_value=mock_subprocess):
        result = builder.push(tag)
    
    assert result == tag, "Should return the pushed tag"


def test_push_error_docker_push_failure(temp_project_dir):
    """Push fails when Docker push command returns non-zero"""
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    tag = "registry.example.com/test:latest"
    
    mock_subprocess = MagicMock()
    mock_subprocess.returncode = 1
    mock_subprocess.stderr = "Push failed"
    
    with patch('subprocess.run', return_value=mock_subprocess):
        with pytest.raises((DockerPushFailure, subprocess.CalledProcessError, Exception)):
            builder.push(tag)


def test_push_error_auth_failure(temp_project_dir):
    """Push fails when user not authenticated to registry"""
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    tag = "registry.example.com/test:latest"
    
    mock_subprocess = MagicMock()
    mock_subprocess.returncode = 1
    mock_subprocess.stderr = "authentication required"
    
    with patch('subprocess.run', return_value=mock_subprocess):
        with pytest.raises((DockerPushFailure, subprocess.CalledProcessError, Exception)):
            builder.push(tag)


# ==============================================================================
# list_images TESTS
# ==============================================================================

def test_list_images_happy_path(temp_project_dir):
    """List all built images from images.json"""
    images_file = temp_project_dir / ".baton" / "images.json"
    images_data = [
        {
            "node_name": "node1",
            "tag": "test:v1",
            "built_at": "2024-01-01T00:00:00",
            "digest": "sha256:abc"
        },
        {
            "node_name": "node2",
            "tag": "test:v2",
            "built_at": "2024-01-02T00:00:00",
            "digest": "sha256:def"
        }
    ]
    images_file.write_text(json.dumps(images_data))
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    result = builder.list_images()
    
    assert len(result) > 0, "Should return non-empty list"
    assert all(hasattr(img, 'node_name') for img in result), "All items should have node_name"
    assert len(result) == 2, "Should return correct number of images"


def test_list_images_edge_case_empty(temp_project_dir):
    """List images returns empty list when images.json doesn't exist"""
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    result = builder.list_images()
    
    assert result == [], "Should return empty list when file doesn't exist"


def test_list_images_error_json_decode(temp_project_dir):
    """List images fails when images.json contains invalid JSON"""
    images_file = temp_project_dir / ".baton" / "images.json"
    images_file.write_text('{"invalid": json}')  # Malformed JSON
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    with pytest.raises((json.JSONDecodeError, Exception)):
        builder.list_images()


def test_list_images_error_file_read(temp_project_dir):
    """List images fails when images.json cannot be read"""
    images_file = temp_project_dir / ".baton" / "images.json"
    images_file.write_text('[]')
    
    # Make file unreadable
    if os.name != 'nt':  # Skip on Windows
        os.chmod(images_file, 0o000)
        
        builder = ImageBuilder(temp_project_dir, "test_circuit")
        
        with pytest.raises((FileReadError, PermissionError, OSError)):
            builder.list_images()
        
        # Restore permissions for cleanup
        os.chmod(images_file, 0o644)


# ==============================================================================
# _save_image_info TESTS
# ==============================================================================

def test_save_image_info_happy_path_new(temp_project_dir, sample_image_info):
    """Save new image info to images.json"""
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    builder._save_image_info(sample_image_info)
    
    images_file = temp_project_dir / ".baton" / "images.json"
    assert images_file.exists(), "images.json should be created"
    
    with open(images_file) as f:
        data = json.load(f)
    
    assert len(data) == 1, "Should have one entry"
    assert data[0]["node_name"] == sample_image_info.node_name, "Should save correct node_name"


def test_save_image_info_happy_path_update(temp_project_dir):
    """Update existing image info in images.json"""
    images_file = temp_project_dir / ".baton" / "images.json"
    existing_data = [
        {
            "node_name": "existing",
            "tag": "old:latest",
            "built_at": "2024-01-01T00:00:00",
            "digest": "sha256:old"
        }
    ]
    images_file.write_text(json.dumps(existing_data))
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    updated_info = ImageInfo(
        node_name="existing",
        tag="new:latest",
        built_at="2024-01-02T00:00:00",
        digest="sha256:new"
    )
    
    builder._save_image_info(updated_info)
    
    with open(images_file) as f:
        data = json.load(f)
    
    assert len(data) == 1, "Should still have one entry (updated, not duplicated)"
    assert data[0]["tag"] == "new:latest", "Should update existing entry"
    assert data[0]["digest"] == "sha256:new", "Should update digest"


def test_save_image_info_error_file_write(temp_project_dir, sample_image_info):
    """Save image info fails when cannot write to images.json"""
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    with patch('builtins.open', side_effect=PermissionError("Cannot write")):
        with pytest.raises((FileWriteError, PermissionError, OSError)):
            builder._save_image_info(sample_image_info)


def test_save_image_info_error_json_decode(temp_project_dir, sample_image_info):
    """Save image info fails when existing images.json has invalid JSON"""
    images_file = temp_project_dir / ".baton" / "images.json"
    images_file.write_text('{"invalid": json}')  # Malformed JSON
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    with pytest.raises((json.JSONDecodeError, Exception)):
        builder._save_image_info(sample_image_info)


# ==============================================================================
# _detect_python_entry TESTS
# ==============================================================================

def test_detect_python_entry_happy_path_pyproject(temp_project_dir):
    """Detect Python entry point from pyproject.toml"""
    service_dir = temp_project_dir / "python_service"
    service_dir.mkdir()
    pyproject = service_dir / "pyproject.toml"
    pyproject.write_text("""
[project.scripts]
myapp = "myapp.main:run"
""")
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    result = builder._detect_python_entry(service_dir)
    
    assert isinstance(result, list), "Should return a list"
    assert len(result) > 0, "Should return non-empty list"


def test_detect_python_entry_happy_path_app_py(temp_project_dir):
    """Detect Python entry point from app.py"""
    service_dir = temp_project_dir / "python_service"
    service_dir.mkdir()
    app_py = service_dir / "app.py"
    app_py.write_text("# App entry point")
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    result = builder._detect_python_entry(service_dir)
    
    assert isinstance(result, list), "Should return a list"
    # Should detect app.py or use app in command
    result_str = " ".join(result)
    assert "app" in result_str, "Should reference app in command"


def test_detect_python_entry_edge_case_default(temp_project_dir):
    """Detect Python entry defaults when no entry point found"""
    service_dir = temp_project_dir / "empty_service"
    service_dir.mkdir()
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    result = builder._detect_python_entry(service_dir)
    
    assert result == ["python", "-m", "app"], "Should return default command"


def test_detect_python_entry_error_file_read(temp_project_dir):
    """Detect Python entry fails when pyproject.toml cannot be read"""
    service_dir = temp_project_dir / "python_service"
    service_dir.mkdir()
    pyproject = service_dir / "pyproject.toml"
    pyproject.write_text("[project]")
    
    if os.name != 'nt':  # Skip on Windows
        os.chmod(pyproject, 0o000)
        
        builder = ImageBuilder(temp_project_dir, "test_circuit")
        
        with pytest.raises((FileReadError, PermissionError, OSError)):
            builder._detect_python_entry(service_dir)
        
        # Restore permissions
        os.chmod(pyproject, 0o644)


# ==============================================================================
# _detect_node_entry TESTS
# ==============================================================================

def test_detect_node_entry_happy_path_package_json(temp_project_dir):
    """Detect Node.js entry point from package.json"""
    service_dir = temp_project_dir / "node_service"
    service_dir.mkdir()
    package_json = service_dir / "package.json"
    package_json.write_text(json.dumps({
        "name": "test",
        "main": "server.js"
    }))
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    result = builder._detect_node_entry(service_dir)
    
    assert isinstance(result, str), "Should return a string"
    assert len(result) > 0, "Should return non-empty string"


def test_detect_node_entry_happy_path_index_js(temp_project_dir):
    """Detect Node.js entry point from index.js"""
    service_dir = temp_project_dir / "node_service"
    service_dir.mkdir()
    index_js = service_dir / "index.js"
    index_js.write_text("// Entry point")
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    result = builder._detect_node_entry(service_dir)
    
    assert isinstance(result, str), "Should return a string"
    assert "index.js" in result or result == "index.js", "Should detect index.js"


def test_detect_node_entry_edge_case_default(temp_project_dir):
    """Detect Node.js entry defaults to index.js when no entry point found"""
    service_dir = temp_project_dir / "empty_service"
    service_dir.mkdir()
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    result = builder._detect_node_entry(service_dir)
    
    assert result == "index.js", "Should default to index.js"


def test_detect_node_entry_error_json_decode(temp_project_dir):
    """Detect Node.js entry fails when package.json has invalid JSON"""
    service_dir = temp_project_dir / "node_service"
    service_dir.mkdir()
    package_json = service_dir / "package.json"
    package_json.write_text('{"invalid": json}')  # Malformed JSON
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    with pytest.raises((json.JSONDecodeError, Exception)):
        builder._detect_node_entry(service_dir)


def test_detect_node_entry_error_file_read(temp_project_dir):
    """Detect Node.js entry fails when package.json cannot be read"""
    service_dir = temp_project_dir / "node_service"
    service_dir.mkdir()
    package_json = service_dir / "package.json"
    package_json.write_text('{}')
    
    if os.name != 'nt':  # Skip on Windows
        os.chmod(package_json, 0o000)
        
        builder = ImageBuilder(temp_project_dir, "test_circuit")
        
        with pytest.raises((FileReadError, PermissionError, OSError)):
            builder._detect_node_entry(service_dir)
        
        # Restore permissions
        os.chmod(package_json, 0o644)


# ==============================================================================
# INVARIANT TESTS
# ==============================================================================

def test_invariant_images_file_constant():
    """Verify IMAGES_FILE constant is always 'images.json'"""
    assert IMAGES_FILE == "images.json", "IMAGES_FILE constant must be 'images.json'"


def test_invariant_python_dockerfile_base_image(temp_project_dir):
    """Verify Python Dockerfile uses python:3.12-slim and exposes 8080"""
    service_dir = temp_project_dir / "service"
    service_dir.mkdir()
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    with patch.object(builder, 'detect_runtime', return_value='python'):
        result = builder.generate_dockerfile("test_node", service_dir)
    
    dockerfile_content = result.read_text()
    
    assert "python:3.12-slim" in dockerfile_content, "Python Dockerfile must use python:3.12-slim"
    assert "EXPOSE 8080" in dockerfile_content, "Python Dockerfile must expose port 8080"
    assert "WORKDIR /app" in dockerfile_content, "Python Dockerfile must set WORKDIR /app"
    assert "PORT" in dockerfile_content and "8080" in dockerfile_content, "Python Dockerfile must set PORT=8080"


def test_invariant_node_dockerfile_base_image(temp_project_dir):
    """Verify Node Dockerfile uses node:20-slim and exposes 8080"""
    service_dir = temp_project_dir / "service"
    service_dir.mkdir()
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    with patch.object(builder, 'detect_runtime', return_value='node'):
        result = builder.generate_dockerfile("test_node", service_dir)
    
    dockerfile_content = result.read_text()
    
    assert "node:20-slim" in dockerfile_content, "Node Dockerfile must use node:20-slim"
    assert "EXPOSE 8080" in dockerfile_content, "Node Dockerfile must expose port 8080"
    assert "WORKDIR /app" in dockerfile_content, "Node Dockerfile must set WORKDIR /app"
    assert "PORT" in dockerfile_content and "8080" in dockerfile_content, "Node Dockerfile must set PORT=8080"


def test_invariant_dockerfile_location(temp_project_dir):
    """Verify Dockerfiles are stored in .baton/dockerfiles/"""
    service_dir = temp_project_dir / "service"
    service_dir.mkdir()
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    with patch.object(builder, 'detect_runtime', return_value='python'):
        result = builder.generate_dockerfile("test_node", service_dir)
    
    assert ".baton/dockerfiles/" in str(result) or ".baton\\dockerfiles\\" in str(result), \
        "Dockerfiles must be stored in .baton/dockerfiles/"
    assert result.parent.name == "dockerfiles", "Dockerfile parent directory must be 'dockerfiles'"


def test_invariant_images_metadata_location(temp_project_dir, sample_image_info):
    """Verify image metadata is stored in .baton/images.json"""
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    
    builder._save_image_info(sample_image_info)
    
    images_file = temp_project_dir / ".baton" / "images.json"
    assert images_file.exists(), "Image metadata must be stored in .baton/images.json"
    assert images_file.name == "images.json", "Image metadata file must be named 'images.json'"
    assert ".baton" in str(images_file.parent), "Image metadata must be in .baton directory"


# ==============================================================================
# ADDITIONAL EDGE CASE TESTS
# ==============================================================================

def test_generate_dockerfile_creates_directory_if_missing(tmp_path):
    """Verify generate_dockerfile creates dockerfiles directory if it doesn't exist"""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    baton_dir = project_dir / ".baton"
    baton_dir.mkdir()
    # Don't create dockerfiles directory
    
    service_dir = project_dir / "service"
    service_dir.mkdir()
    
    builder = ImageBuilder(project_dir, "test_circuit")
    
    with patch.object(builder, 'detect_runtime', return_value='python'):
        result = builder.generate_dockerfile("test_node", service_dir)
    
    dockerfiles_dir = baton_dir / "dockerfiles"
    assert dockerfiles_dir.exists(), "Should create dockerfiles directory if missing"
    assert result.exists(), "Should create Dockerfile"


def test_build_with_custom_tag(temp_project_dir):
    """Build Docker image with custom tag format"""
    service_dir = temp_project_dir / "service"
    service_dir.mkdir()
    
    builder = ImageBuilder(temp_project_dir, "custom_circuit")
    custom_tag = "registry.io/custom_circuit-node:v1.2.3"
    
    mock_subprocess = MagicMock()
    mock_subprocess.returncode = 0
    
    with patch('subprocess.run', return_value=mock_subprocess):
        with patch.object(builder, 'generate_dockerfile', return_value=temp_project_dir / ".baton" / "dockerfiles" / "Dockerfile.node"):
            with patch.object(builder, '_save_image_info'):
                with patch('subprocess.check_output', return_value=b'sha256:custom123\n'):
                    result = builder.build("node", service_dir, custom_tag)
    
    assert result.tag == custom_tag, "Should support custom tag format"


def test_list_images_with_multiple_entries(temp_project_dir):
    """List images correctly handles multiple entries"""
    images_file = temp_project_dir / ".baton" / "images.json"
    images_data = [
        {"node_name": f"node{i}", "tag": f"tag{i}", "built_at": "2024-01-01T00:00:00", "digest": f"sha256:abc{i}"}
        for i in range(5)
    ]
    images_file.write_text(json.dumps(images_data))
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    result = builder.list_images()
    
    assert len(result) == 5, "Should return all images"
    node_names = [img.node_name for img in result]
    assert len(set(node_names)) == 5, "All node names should be unique"


def test_save_image_info_preserves_other_entries(temp_project_dir):
    """Verify _save_image_info doesn't affect other entries when updating"""
    images_file = temp_project_dir / ".baton" / "images.json"
    existing_data = [
        {"node_name": "node1", "tag": "tag1", "built_at": "2024-01-01T00:00:00", "digest": "sha256:abc"},
        {"node_name": "node2", "tag": "tag2", "built_at": "2024-01-01T00:00:00", "digest": "sha256:def"},
        {"node_name": "node3", "tag": "tag3", "built_at": "2024-01-01T00:00:00", "digest": "sha256:ghi"}
    ]
    images_file.write_text(json.dumps(existing_data))
    
    builder = ImageBuilder(temp_project_dir, "test_circuit")
    updated_info = ImageInfo(
        node_name="node2",
        tag="updated_tag",
        built_at="2024-01-02T00:00:00",
        digest="sha256:updated"
    )
    
    builder._save_image_info(updated_info)
    
    with open(images_file) as f:
        data = json.load(f)
    
    assert len(data) == 3, "Should still have 3 entries"
    assert data[0]["node_name"] == "node1", "First entry should be unchanged"
    assert data[2]["node_name"] == "node3", "Third entry should be unchanged"
    assert data[1]["tag"] == "updated_tag", "Second entry should be updated"
