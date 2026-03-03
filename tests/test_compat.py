"""Tests for static compatibility analysis."""

from __future__ import annotations

from pathlib import Path

import yaml

from baton.compat import check_compatibility
from baton.schemas import DependencySpec, ServiceManifest


def _write_spec(path: Path, spec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(spec, f)


class TestCheckCompatibility:
    def test_compatible_services(self, tmp_path: Path):
        """Consumer expects subset of what provider exposes."""
        provider_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "integer"},
                                                "name": {"type": "string"},
                                                "email": {"type": "string"},
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        expected_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "required": ["id", "name"],
                                            "properties": {
                                                "id": {"type": "integer"},
                                                "name": {"type": "string"},
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        _write_spec(tmp_path / "provider.yaml", provider_spec)
        _write_spec(tmp_path / "expected.yaml", expected_spec)

        provider = ServiceManifest(name="users-api", api_spec="provider.yaml")
        consumer = ServiceManifest(
            name="web",
            dependencies=[
                DependencySpec(name="users-api", expected_api="expected.yaml")
            ],
        )
        report = check_compatibility(provider, [consumer], base_dir=tmp_path)
        assert report.compatible is True
        assert len(report.issues) == 0

    def test_missing_path(self, tmp_path: Path):
        provider_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/health": {
                    "get": {"responses": {"200": {}}}
                }
            },
        }
        expected_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "get": {"responses": {"200": {}}}
                }
            },
        }
        _write_spec(tmp_path / "provider.yaml", provider_spec)
        _write_spec(tmp_path / "expected.yaml", expected_spec)

        provider = ServiceManifest(name="api", api_spec="provider.yaml")
        consumer = ServiceManifest(
            name="web",
            dependencies=[DependencySpec(name="api", expected_api="expected.yaml")],
        )
        report = check_compatibility(provider, [consumer], base_dir=tmp_path)
        assert report.compatible is False
        assert len(report.issues) == 1
        assert "Path '/users'" in report.issues[0].detail

    def test_missing_method(self, tmp_path: Path):
        provider_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "get": {"responses": {"200": {}}}
                }
            },
        }
        expected_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "post": {"responses": {"201": {}}}
                }
            },
        }
        _write_spec(tmp_path / "provider.yaml", provider_spec)
        _write_spec(tmp_path / "expected.yaml", expected_spec)

        provider = ServiceManifest(name="api", api_spec="provider.yaml")
        consumer = ServiceManifest(
            name="web",
            dependencies=[DependencySpec(name="api", expected_api="expected.yaml")],
        )
        report = check_compatibility(provider, [consumer], base_dir=tmp_path)
        assert report.compatible is False
        assert "POST" in report.issues[0].detail

    def test_missing_required_property(self, tmp_path: Path):
        provider_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "integer"},
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        expected_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "required": ["id", "name"],
                                            "properties": {
                                                "id": {"type": "integer"},
                                                "name": {"type": "string"},
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        _write_spec(tmp_path / "provider.yaml", provider_spec)
        _write_spec(tmp_path / "expected.yaml", expected_spec)

        provider = ServiceManifest(name="api", api_spec="provider.yaml")
        consumer = ServiceManifest(
            name="web",
            dependencies=[DependencySpec(name="api", expected_api="expected.yaml")],
        )
        report = check_compatibility(provider, [consumer], base_dir=tmp_path)
        assert report.compatible is False
        assert any("name" in str(i.detail) for i in report.issues)

    def test_extra_properties_ok(self, tmp_path: Path):
        """Provider has extra fields consumer doesn't expect -- compatible."""
        provider_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "integer"},
                                                "name": {"type": "string"},
                                                "email": {"type": "string"},
                                                "avatar": {"type": "string"},
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        expected_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "required": ["id"],
                                            "properties": {
                                                "id": {"type": "integer"},
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        _write_spec(tmp_path / "provider.yaml", provider_spec)
        _write_spec(tmp_path / "expected.yaml", expected_spec)

        provider = ServiceManifest(name="api", api_spec="provider.yaml")
        consumer = ServiceManifest(
            name="web",
            dependencies=[DependencySpec(name="api", expected_api="expected.yaml")],
        )
        report = check_compatibility(provider, [consumer], base_dir=tmp_path)
        assert report.compatible is True

    def test_type_mismatch(self, tmp_path: Path):
        provider_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object", "properties": {}}
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        expected_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "array", "items": {}}
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        _write_spec(tmp_path / "provider.yaml", provider_spec)
        _write_spec(tmp_path / "expected.yaml", expected_spec)

        provider = ServiceManifest(name="api", api_spec="provider.yaml")
        consumer = ServiceManifest(
            name="web",
            dependencies=[DependencySpec(name="api", expected_api="expected.yaml")],
        )
        report = check_compatibility(provider, [consumer], base_dir=tmp_path)
        assert report.compatible is False
        assert "Type mismatch" in report.issues[0].detail

    def test_no_expected_api(self, tmp_path: Path):
        """Consumer doesn't specify expected_api -- nothing to check."""
        provider = ServiceManifest(name="api", api_spec="specs/api.yaml")
        consumer = ServiceManifest(
            name="web",
            dependencies=[DependencySpec(name="api")],  # no expected_api
        )
        report = check_compatibility(provider, [consumer], base_dir=tmp_path)
        assert report.compatible is True
        assert len(report.issues) == 0

    def test_no_provider_api_spec(self, tmp_path: Path):
        """Provider has no api_spec -- issues for any consumer expectations."""
        expected_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {"get": {"responses": {"200": {}}}},
            },
        }
        _write_spec(tmp_path / "expected.yaml", expected_spec)

        provider = ServiceManifest(name="api")  # no api_spec
        consumer = ServiceManifest(
            name="web",
            dependencies=[DependencySpec(name="api", expected_api="expected.yaml")],
        )
        report = check_compatibility(provider, [consumer], base_dir=tmp_path)
        assert report.compatible is False

    def test_multiple_consumers(self, tmp_path: Path):
        provider_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {"get": {"responses": {"200": {}}}},
            },
        }
        expected_ok = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {"get": {"responses": {"200": {}}}},
            },
        }
        expected_bad = {
            "openapi": "3.0.0",
            "paths": {
                "/orders": {"get": {"responses": {"200": {}}}},
            },
        }
        _write_spec(tmp_path / "provider.yaml", provider_spec)
        _write_spec(tmp_path / "expected-ok.yaml", expected_ok)
        _write_spec(tmp_path / "expected-bad.yaml", expected_bad)

        provider = ServiceManifest(name="api", api_spec="provider.yaml")
        consumer_ok = ServiceManifest(
            name="web",
            dependencies=[DependencySpec(name="api", expected_api="expected-ok.yaml")],
        )
        consumer_bad = ServiceManifest(
            name="mobile",
            dependencies=[DependencySpec(name="api", expected_api="expected-bad.yaml")],
        )
        report = check_compatibility(
            provider, [consumer_ok, consumer_bad], base_dir=tmp_path
        )
        assert report.compatible is False
        assert len(report.issues) == 1
        assert report.issues[0].consumer == "mobile"

    def test_array_items_check(self, tmp_path: Path):
        provider_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "id": {"type": "integer"},
                                                },
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        expected_spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "required": ["id", "name"],
                                                "properties": {
                                                    "id": {"type": "integer"},
                                                    "name": {"type": "string"},
                                                },
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        _write_spec(tmp_path / "provider.yaml", provider_spec)
        _write_spec(tmp_path / "expected.yaml", expected_spec)

        provider = ServiceManifest(name="api", api_spec="provider.yaml")
        consumer = ServiceManifest(
            name="web",
            dependencies=[DependencySpec(name="api", expected_api="expected.yaml")],
        )
        report = check_compatibility(provider, [consumer], base_dir=tmp_path)
        assert report.compatible is False
        assert any("name" in str(i.detail) for i in report.issues)

    def test_optional_dependency_skipped(self, tmp_path: Path):
        """Optional deps from unrelated consumers shouldn't generate issues."""
        provider = ServiceManifest(name="api", api_spec="specs/api.yaml")
        consumer = ServiceManifest(
            name="web",
            dependencies=[
                DependencySpec(name="other-service", optional=True),
            ],
        )
        report = check_compatibility(provider, [consumer], base_dir=tmp_path)
        assert report.compatible is True
        assert len(report.issues) == 0
