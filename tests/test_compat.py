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


# ---------------------------------------------------------------------------
# Runtime validation tests
# ---------------------------------------------------------------------------

import asyncio

from baton.compat import (
    RuntimeValidationResult,
    validate_service_runtime,
    _parse_probe_status,
)


async def _start_test_server(
    port: int, paths: dict[str, set[str]] | None = None
) -> asyncio.Server:
    """Start a test HTTP server that responds to specified paths/methods.

    Args:
        port: Port to listen on
        paths: Dict of {path: {method, ...}} that return 200. Everything else
               returns 404.  If None, returns 200 for everything.
    """

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            # Read remaining headers
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b""):
                    break

            parts = request_line.decode("ascii", errors="replace").strip().split()
            method = parts[0] if parts else ""
            path = parts[1] if len(parts) > 1 else ""

            if paths is None or (path in paths and method in paths[path]):
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Length: 2\r\n"
                    b"Connection: close\r\n\r\nOK"
                )
            elif path in paths:
                response = (
                    b"HTTP/1.1 405 Method Not Allowed\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n\r\n"
                )
            else:
                response = (
                    b"HTTP/1.1 404 Not Found\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n\r\n"
                )

            writer.write(response)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", port)
    return server


class TestParseProbeStatus:
    def test_parse_200(self):
        raw = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"
        assert _parse_probe_status(raw) == 200

    def test_parse_404(self):
        raw = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"
        assert _parse_probe_status(raw) == 404

    def test_parse_empty(self):
        assert _parse_probe_status(b"") == 0

    def test_parse_garbage(self):
        assert _parse_probe_status(b"not-http-at-all") == 0


class TestValidateServiceRuntime:
    async def test_unreachable_service(self, tmp_path: Path):
        """No server running -- should report unreachable."""
        spec = {
            "openapi": "3.0.0",
            "paths": {"/health": {"get": {"responses": {"200": {}}}}},
        }
        _write_spec(tmp_path / "api.yaml", spec)

        result = await validate_service_runtime(
            "127.0.0.1", 19500, "api.yaml", base_dir=tmp_path, timeout=1.0
        )
        assert result.compatible is False
        assert result.reachable is False
        assert len(result.issues) >= 1
        assert "unreachable" in result.issues[0].detail.lower()

    async def test_all_paths_implemented(self, tmp_path: Path):
        """Server implements all contract paths -- compatible."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {"get": {"responses": {"200": {}}}},
                "/health": {"get": {"responses": {"200": {}}}},
            },
        }
        _write_spec(tmp_path / "api.yaml", spec)

        server = await _start_test_server(
            19501,
            paths={"/users": {"GET"}, "/health": {"GET"}},
        )
        try:
            result = await validate_service_runtime(
                "127.0.0.1", 19501, "api.yaml", base_dir=tmp_path, timeout=2.0
            )
            assert result.compatible is True
            assert result.reachable is True
            assert result.probed_endpoints == 2
            assert len(result.issues) == 0
        finally:
            server.close()
            await server.wait_closed()

    async def test_missing_path(self, tmp_path: Path):
        """Server doesn't implement a path -- compatible=False with 404."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {"get": {"responses": {"200": {}}}},
                "/orders": {"get": {"responses": {"200": {}}}},
            },
        }
        _write_spec(tmp_path / "api.yaml", spec)

        # Server only implements /users, not /orders
        server = await _start_test_server(
            19502,
            paths={"/users": {"GET"}},
        )
        try:
            result = await validate_service_runtime(
                "127.0.0.1", 19502, "api.yaml", base_dir=tmp_path, timeout=2.0
            )
            assert result.compatible is False
            assert result.reachable is True
            assert result.probed_endpoints == 2
            assert any("404" in issue.detail for issue in result.issues)
        finally:
            server.close()
            await server.wait_closed()

    async def test_wrong_method(self, tmp_path: Path):
        """Server has path but wrong method -- compatible=False with 405."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/users": {"post": {"responses": {"201": {}}}},
            },
        }
        _write_spec(tmp_path / "api.yaml", spec)

        # Server only supports GET on /users, not POST
        server = await _start_test_server(
            19503,
            paths={"/users": {"GET"}},
        )
        try:
            result = await validate_service_runtime(
                "127.0.0.1", 19503, "api.yaml", base_dir=tmp_path, timeout=2.0
            )
            assert result.compatible is False
            assert result.reachable is True
            assert any("405" in issue.detail for issue in result.issues)
        finally:
            server.close()
            await server.wait_closed()

    async def test_no_contract_paths(self, tmp_path: Path):
        """Empty contract -- compatible=True, reachable=True."""
        spec = {"openapi": "3.0.0", "paths": {}}
        _write_spec(tmp_path / "api.yaml", spec)

        server = await _start_test_server(19504)
        try:
            result = await validate_service_runtime(
                "127.0.0.1", 19504, "api.yaml", base_dir=tmp_path, timeout=2.0
            )
            assert result.compatible is True
            assert result.reachable is True
            assert result.probed_endpoints == 0
        finally:
            server.close()
            await server.wait_closed()

    async def test_contract_file_missing(self, tmp_path: Path):
        """Nonexistent spec file -- compatible=True (no paths to check)."""
        result = await validate_service_runtime(
            "127.0.0.1", 19505, "nonexistent.yaml", base_dir=tmp_path, timeout=1.0
        )
        assert result.compatible is True
        assert result.probed_endpoints == 0
