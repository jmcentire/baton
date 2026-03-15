"""Tests for Ledger integration."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from baton.schemas import LedgerConfig


class TestLedgerConfig:
    def test_defaults(self):
        config = LedgerConfig()
        assert config.api_endpoint == ""
        assert config.mock_from_ledger is True

    def test_custom(self):
        config = LedgerConfig(api_endpoint="http://localhost:7701", mock_from_ledger=False)
        assert config.api_endpoint == "http://localhost:7701"
        assert config.mock_from_ledger is False


class TestLedgerClient:
    @pytest.mark.asyncio
    async def test_unreachable_returns_empty(self):
        from baton.ledger import LedgerClient
        client = LedgerClient("http://127.0.0.1:19998")
        result = await client.get_egress_export()
        assert result == []

    @pytest.mark.asyncio
    async def test_mock_records_unreachable(self):
        from baton.ledger import LedgerClient
        client = LedgerClient("http://127.0.0.1:19998")
        result = await client.get_mock_records(["PII"])
        assert result == []


class TestFieldMasking:
    def test_mask_replaces_field(self):
        from baton.adapter import _apply_field_masks
        response = b'HTTP/1.1 200 OK\r\nContent-Length: 27\r\n\r\n{"ssn":"123-45-6789","ok":1}'
        masks = [("ssn", "[ENCRYPTED]")]
        result = _apply_field_masks(response, masks)
        assert b"[ENCRYPTED]" in result
        assert b"123-45-6789" not in result

    def test_mask_updates_content_length(self):
        from baton.adapter import _apply_field_masks
        response = b'HTTP/1.1 200 OK\r\nContent-Length: 27\r\n\r\n{"ssn":"123-45-6789","ok":1}'
        masks = [("ssn", "[ENCRYPTED]")]
        result = _apply_field_masks(response, masks)
        # Content-Length should match new body
        import json
        parts = result.split(b"\r\n\r\n", 1)
        body = parts[1]
        for line in parts[0].split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                cl = int(line.split(b":", 1)[1].strip())
                assert cl == len(body)

    def test_mask_no_match_unchanged(self):
        from baton.adapter import _apply_field_masks
        response = b'HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\n{"name":"ok"}'
        masks = [("ssn", "[ENCRYPTED]")]
        result = _apply_field_masks(response, masks)
        assert result == response

    def test_mask_non_json_unchanged(self):
        from baton.adapter import _apply_field_masks
        response = b'HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello'
        masks = [("ssn", "[ENCRYPTED]")]
        result = _apply_field_masks(response, masks)
        assert result == response


class TestLedgerConfigRoundTrip:
    def test_roundtrip(self, tmp_path: Path):
        from baton.config import load_circuit_config, save_circuit_config
        from baton.schemas import CircuitConfig, NodeSpec, LedgerConfig as LC

        config = CircuitConfig(
            nodes=[NodeSpec(name="api", port=8001)],
            ledger=LC(api_endpoint="http://localhost:7701"),
        )
        save_circuit_config(config, tmp_path)
        loaded = load_circuit_config(tmp_path)
        assert loaded.ledger.api_endpoint == "http://localhost:7701"
        assert loaded.ledger.mock_from_ledger is True
