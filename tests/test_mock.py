"""Tests for mock server generation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from baton.mock import MockServer, generate_instance, load_routes, parse_openapi


class TestGenerateInstance:
    def test_string(self):
        result = generate_instance({"type": "string"})
        assert isinstance(result, str)
        assert len(result) >= 5

    def test_string_with_example(self):
        result = generate_instance({"type": "string", "example": "hello"})
        assert result == "hello"

    def test_integer(self):
        result = generate_instance({"type": "integer"})
        assert isinstance(result, int)

    def test_integer_range(self):
        result = generate_instance({"type": "integer", "minimum": 10, "maximum": 10})
        assert result == 10

    def test_number(self):
        result = generate_instance({"type": "number"})
        assert isinstance(result, float)

    def test_boolean(self):
        result = generate_instance({"type": "boolean"})
        assert result is True

    def test_array(self):
        result = generate_instance({"type": "array", "items": {"type": "integer"}})
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_object(self):
        result = generate_instance({
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name", "age"],
        })
        assert isinstance(result, dict)
        assert "name" in result
        assert "age" in result

    def test_enum(self):
        result = generate_instance({"type": "string", "enum": ["a", "b", "c"]})
        assert result == "a"

    def test_default(self):
        result = generate_instance({"type": "string", "default": "fallback"})
        assert result == "fallback"

    def test_string_format_email(self):
        result = generate_instance({"type": "string", "format": "email"})
        assert "@" in result

    def test_string_format_date(self):
        result = generate_instance({"type": "string", "format": "date"})
        assert "2026" in result

    def test_null_type(self):
        result = generate_instance({"type": "null"})
        assert result is None


class TestParseOpenAPI:
    def test_parse_simple(self, tmp_path: Path):
        spec = {
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
        spec_path = tmp_path / "api.yaml"
        import yaml
        with open(spec_path, "w") as f:
            yaml.dump(spec, f)

        routes = parse_openapi(str(spec_path))
        assert "/users" in routes
        assert "GET" in routes["/users"]
        body = routes["/users"]["GET"]
        assert isinstance(body, list)

    def test_parse_with_ref(self, tmp_path: Path):
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/user": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/User"}
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "components": {
                "schemas": {
                    "User": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "email": {"type": "string", "format": "email"},
                        },
                        "required": ["id", "email"],
                    }
                }
            },
        }
        spec_path = tmp_path / "api.json"
        with open(spec_path, "w") as f:
            json.dump(spec, f)

        routes = parse_openapi(str(spec_path))
        body = routes["/user"]["GET"]
        assert "id" in body
        assert "email" in body

    def test_parse_with_example(self, tmp_path: Path):
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/status": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "example": {"status": "ok", "version": "1.0"},
                                        "schema": {"type": "object"},
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        spec_path = tmp_path / "api.yaml"
        import yaml
        with open(spec_path, "w") as f:
            yaml.dump(spec, f)

        routes = parse_openapi(str(spec_path))
        assert routes["/status"]["GET"] == {"status": "ok", "version": "1.0"}


class TestLoadRoutes:
    def test_load_openapi(self, tmp_path: Path):
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/health": {
                    "get": {
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "example": {"ok": True}
                                    }
                                }
                            }
                        }
                    }
                }
            },
        }
        spec_path = tmp_path / "spec.yaml"
        import yaml
        with open(spec_path, "w") as f:
            yaml.dump(spec, f)

        routes = load_routes(str(spec_path))
        assert "/health" in routes

    def test_load_json_schema(self, tmp_path: Path):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        }
        spec_path = tmp_path / "schema.json"
        with open(spec_path, "w") as f:
            json.dump(schema, f)

        routes = load_routes(str(spec_path))
        assert "/" in routes
        assert "GET" in routes["/"]

    def test_load_missing(self):
        routes = load_routes("/nonexistent/spec.yaml")
        assert routes == {}


class TestMockServer:
    async def test_start_and_stop(self):
        server = MockServer()
        server.add_default_routes(16001)
        await server.start()
        assert server.is_running
        await server.stop()
        assert not server.is_running

    async def test_serves_route(self):
        server = MockServer()
        server.add_routes(16002, {
            "/health": {"GET": {"status": "ok"}},
        })
        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 16002)
            writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            chunks = []
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
            writer.close()

            assert b"200 OK" in response
            body = response.split(b"\r\n\r\n", 1)[1]
            data = json.loads(body)
            assert data["status"] == "ok"
        finally:
            await server.stop()

    async def test_404_for_unknown_route(self):
        server = MockServer()
        server.add_routes(16003, {
            "/health": {"GET": {"status": "ok"}},
        })
        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 16003)
            writer.write(b"GET /unknown HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            chunks = []
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
            writer.close()
            assert b"404" in response
        finally:
            await server.stop()

    async def test_multiple_ports(self):
        server = MockServer()
        server.add_routes(16004, {"/a": {"GET": {"port": "a"}}})
        server.add_routes(16005, {"/b": {"GET": {"port": "b"}}})
        await server.start()
        try:
            # Port A
            reader, writer = await asyncio.open_connection("127.0.0.1", 16004)
            writer.write(b"GET /a HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            chunks = []
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                chunks.append(chunk)
            resp_a = b"".join(chunks)
            writer.close()

            # Port B
            reader, writer = await asyncio.open_connection("127.0.0.1", 16005)
            writer.write(b"GET /b HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            chunks = []
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                chunks.append(chunk)
            resp_b = b"".join(chunks)
            writer.close()

            body_a = json.loads(resp_a.split(b"\r\n\r\n", 1)[1])
            body_b = json.loads(resp_b.split(b"\r\n\r\n", 1)[1])
            assert body_a["port"] == "a"
            assert body_b["port"] == "b"
        finally:
            await server.stop()

    async def test_default_routes(self):
        server = MockServer()
        server.add_default_routes(16006)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 16006)
            writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            chunks = []
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
            writer.close()
            assert b"200" in response
            body = json.loads(response.split(b"\r\n\r\n", 1)[1])
            assert body["status"] == "ok"
        finally:
            await server.stop()
