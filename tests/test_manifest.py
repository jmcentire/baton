"""Tests for service manifest loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from baton.manifest import MANIFEST_FILENAME, load_manifest
from baton.schemas import NodeRole, ProxyMode


class TestLoadManifest:
    def test_basic(self, tmp_path: Path):
        (tmp_path / MANIFEST_FILENAME).write_text(
            yaml.dump({"name": "api", "version": "1.0.0"})
        )
        m = load_manifest(tmp_path)
        assert m.name == "api"
        assert m.version == "1.0.0"
        assert m.role == NodeRole.SERVICE
        assert m.dependencies == []

    def test_full(self, tmp_path: Path):
        data = {
            "name": "payments",
            "version": "2.1.0",
            "api_spec": "specs/payments.yaml",
            "mock_spec": "specs/payments-mock.yaml",
            "command": "python -m payments",
            "port": 8080,
            "proxy_mode": "http",
            "role": "service",
            "dependencies": [
                {"name": "db", "expected_api": "specs/db-expected.yaml"},
                {"name": "auth"},
            ],
            "metadata": {"team": "platform"},
        }
        (tmp_path / MANIFEST_FILENAME).write_text(yaml.dump(data))
        m = load_manifest(tmp_path)
        assert m.name == "payments"
        assert m.api_spec == "specs/payments.yaml"
        assert m.mock_spec == "specs/payments-mock.yaml"
        assert m.command == "python -m payments"
        assert m.port == 8080
        assert len(m.dependencies) == 2
        assert m.dependencies[0].name == "db"
        assert m.dependencies[0].expected_api == "specs/db-expected.yaml"
        assert m.dependencies[1].name == "auth"
        assert m.metadata["team"] == "platform"

    def test_shorthand_dependencies(self, tmp_path: Path):
        data = {
            "name": "api",
            "dependencies": ["payments", "auth", "db"],
        }
        (tmp_path / MANIFEST_FILENAME).write_text(yaml.dump(data))
        m = load_manifest(tmp_path)
        assert len(m.dependencies) == 3
        assert m.dependencies[0].name == "payments"
        assert m.dependencies[1].name == "auth"
        assert m.dependencies[2].name == "db"
        assert m.dependencies[0].optional is False

    def test_optional_dependency(self, tmp_path: Path):
        data = {
            "name": "api",
            "dependencies": [
                {"name": "cache", "optional": True},
            ],
        }
        (tmp_path / MANIFEST_FILENAME).write_text(yaml.dump(data))
        m = load_manifest(tmp_path)
        assert m.dependencies[0].optional is True

    def test_ingress_role(self, tmp_path: Path):
        data = {"name": "gateway", "role": "ingress"}
        (tmp_path / MANIFEST_FILENAME).write_text(yaml.dump(data))
        m = load_manifest(tmp_path)
        assert m.role == NodeRole.INGRESS

    def test_egress_role(self, tmp_path: Path):
        data = {
            "name": "stripe",
            "role": "egress",
            "api_spec": "specs/stripe.yaml",
        }
        (tmp_path / MANIFEST_FILENAME).write_text(yaml.dump(data))
        m = load_manifest(tmp_path)
        assert m.role == NodeRole.EGRESS
        assert m.api_spec == "specs/stripe.yaml"

    def test_tcp_mode(self, tmp_path: Path):
        data = {"name": "db", "proxy_mode": "tcp", "port": 5432}
        (tmp_path / MANIFEST_FILENAME).write_text(yaml.dump(data))
        m = load_manifest(tmp_path)
        assert m.proxy_mode == ProxyMode.TCP

    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_manifest(tmp_path)

    def test_empty_file(self, tmp_path: Path):
        (tmp_path / MANIFEST_FILENAME).write_text("")
        with pytest.raises(ValueError, match="Empty"):
            load_manifest(tmp_path)

    def test_missing_name(self, tmp_path: Path):
        (tmp_path / MANIFEST_FILENAME).write_text(yaml.dump({"version": "1.0"}))
        with pytest.raises(KeyError):
            load_manifest(tmp_path)

    def test_invalid_name(self, tmp_path: Path):
        (tmp_path / MANIFEST_FILENAME).write_text(yaml.dump({"name": "Bad-Name"}))
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            load_manifest(tmp_path)
