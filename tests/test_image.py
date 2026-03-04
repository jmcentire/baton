"""Tests for the image builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from baton.image import ImageBuilder
from baton.schemas import ImageInfo


class TestDetectRuntime:
    def test_detect_python_pyproject(self, tmp_path: Path):
        svc = tmp_path / "svc"
        svc.mkdir()
        (svc / "pyproject.toml").write_text("[project]\nname = 'myapp'\n")

        builder = ImageBuilder(tmp_path)
        assert builder.detect_runtime(svc) == "python"

    def test_detect_python_requirements(self, tmp_path: Path):
        svc = tmp_path / "svc"
        svc.mkdir()
        (svc / "requirements.txt").write_text("flask\n")

        builder = ImageBuilder(tmp_path)
        assert builder.detect_runtime(svc) == "python"

    def test_detect_node(self, tmp_path: Path):
        svc = tmp_path / "svc"
        svc.mkdir()
        (svc / "package.json").write_text('{"name": "myapp"}')

        builder = ImageBuilder(tmp_path)
        assert builder.detect_runtime(svc) == "node"

    def test_detect_default_python(self, tmp_path: Path):
        svc = tmp_path / "svc"
        svc.mkdir()

        builder = ImageBuilder(tmp_path)
        assert builder.detect_runtime(svc) == "python"

    def test_node_takes_precedence_over_python(self, tmp_path: Path):
        """If both package.json and pyproject.toml exist, node wins."""
        svc = tmp_path / "svc"
        svc.mkdir()
        (svc / "package.json").write_text('{"name": "myapp"}')
        (svc / "pyproject.toml").write_text("[project]\n")

        builder = ImageBuilder(tmp_path)
        assert builder.detect_runtime(svc) == "node"


class TestGenerateDockerfile:
    def test_python_dockerfile(self, tmp_path: Path):
        svc = tmp_path / "svc"
        svc.mkdir()
        (svc / "pyproject.toml").write_text("[project]\nname = 'myapp'\n")
        (svc / "app.py").write_text("print('hello')")

        builder = ImageBuilder(tmp_path)
        path = builder.generate_dockerfile("api", svc)

        assert path.exists()
        content = path.read_text()
        assert "python:3.12-slim" in content
        assert "PORT=8080" in content
        assert "app.py" in content

    def test_node_dockerfile(self, tmp_path: Path):
        svc = tmp_path / "svc"
        svc.mkdir()
        (svc / "package.json").write_text(json.dumps({
            "name": "myapp",
            "main": "server.js",
        }))

        builder = ImageBuilder(tmp_path)
        path = builder.generate_dockerfile("web", svc)

        assert path.exists()
        content = path.read_text()
        assert "node:20-slim" in content
        assert "npm ci" in content
        assert "server.js" in content

    def test_dockerfile_written_to_baton_dir(self, tmp_path: Path):
        svc = tmp_path / "svc"
        svc.mkdir()

        builder = ImageBuilder(tmp_path)
        path = builder.generate_dockerfile("api", svc)

        assert ".baton/dockerfiles/Dockerfile.api" in str(path)

    def test_python_pyproject_scripts_entry(self, tmp_path: Path):
        svc = tmp_path / "svc"
        svc.mkdir()
        (svc / "pyproject.toml").write_text(
            '[project]\nname = "myapp"\n\n'
            '[project.scripts]\nmyapp = "myapp.cli:main"\n'
        )

        builder = ImageBuilder(tmp_path)
        path = builder.generate_dockerfile("api", svc)
        content = path.read_text()
        assert "myapp.cli" in content

    def test_node_start_script_entry(self, tmp_path: Path):
        svc = tmp_path / "svc"
        svc.mkdir()
        (svc / "package.json").write_text(json.dumps({
            "name": "myapp",
            "scripts": {"start": "node dist/main.js"},
        }))

        builder = ImageBuilder(tmp_path)
        path = builder.generate_dockerfile("api", svc)
        content = path.read_text()
        assert "dist/main.js" in content


class TestListImages:
    def test_empty_list(self, tmp_path: Path):
        builder = ImageBuilder(tmp_path)
        assert builder.list_images() == []

    def test_list_saved_images(self, tmp_path: Path):
        baton_dir = tmp_path / ".baton"
        baton_dir.mkdir()
        images = [
            {"node_name": "api", "tag": "myapp-api:latest", "built_at": "2026-01-01", "digest": ""},
            {"node_name": "web", "tag": "myapp-web:latest", "built_at": "2026-01-02", "digest": ""},
        ]
        (baton_dir / "images.json").write_text(json.dumps(images))

        builder = ImageBuilder(tmp_path)
        result = builder.list_images()
        assert len(result) == 2
        assert result[0].node_name == "api"
        assert result[1].node_name == "web"


class TestSaveImageInfo:
    def test_save_creates_file(self, tmp_path: Path):
        builder = ImageBuilder(tmp_path)
        info = ImageInfo(node_name="api", tag="test:latest", built_at="now")
        builder._save_image_info(info)

        path = tmp_path / ".baton" / "images.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["node_name"] == "api"

    def test_save_updates_existing(self, tmp_path: Path):
        builder = ImageBuilder(tmp_path)
        info1 = ImageInfo(node_name="api", tag="test:v1", built_at="t1")
        builder._save_image_info(info1)

        info2 = ImageInfo(node_name="api", tag="test:v2", built_at="t2")
        builder._save_image_info(info2)

        path = tmp_path / ".baton" / "images.json"
        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["tag"] == "test:v2"

    def test_save_appends_different_nodes(self, tmp_path: Path):
        builder = ImageBuilder(tmp_path)
        builder._save_image_info(ImageInfo(node_name="api", tag="t:1"))
        builder._save_image_info(ImageInfo(node_name="web", tag="t:2"))

        path = tmp_path / ".baton" / "images.json"
        data = json.loads(path.read_text())
        assert len(data) == 2


class TestImageInfoSchema:
    def test_create_image_info(self):
        info = ImageInfo(node_name="api", tag="test:latest")
        assert info.node_name == "api"
        assert info.tag == "test:latest"
        assert info.built_at == ""
        assert info.digest == ""

    def test_image_info_with_all_fields(self):
        info = ImageInfo(
            node_name="api",
            tag="gcr.io/proj/api:v1",
            built_at="2026-01-01T00:00:00Z",
            digest="sha256:abc123",
        )
        assert info.digest == "sha256:abc123"
