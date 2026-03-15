"""Tests for baton migrate-config (v1 -> v2 schema migration)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from baton.migrate import detect_version, migrate_v1_to_v2, run_migrate


# -- Unit tests for migration logic --


class TestDetectVersion:
    def test_explicit_v1(self):
        assert detect_version({"version": 1}) == 1

    def test_explicit_v2(self):
        assert detect_version({"version": 2}) == 2

    def test_missing_defaults_to_1(self):
        assert detect_version({}) == 1
        assert detect_version({"name": "test"}) == 1


class TestMigrateV1ToV2:
    def test_sets_version_2(self):
        result = migrate_v1_to_v2({"version": 1})
        assert result["version"] == 2

    def test_node_gets_data_access(self):
        raw = {
            "version": 1,
            "nodes": [{"name": "api", "port": 8001}],
        }
        result = migrate_v1_to_v2(raw)
        node = result["nodes"][0]
        assert node["data_access"] == {"reads": [], "writes": []}

    def test_node_gets_authority(self):
        raw = {
            "version": 1,
            "nodes": [{"name": "api", "port": 8001}],
        }
        result = migrate_v1_to_v2(raw)
        assert result["nodes"][0]["authority"] == []

    def test_http_node_gets_openapi_spec(self):
        raw = {
            "version": 1,
            "nodes": [{"name": "api", "port": 8001}],
        }
        result = migrate_v1_to_v2(raw)
        assert result["nodes"][0]["openapi_spec"] == ""

    def test_explicit_http_node_gets_openapi_spec(self):
        raw = {
            "version": 1,
            "nodes": [{"name": "api", "port": 8001, "proxy_mode": "http"}],
        }
        result = migrate_v1_to_v2(raw)
        assert result["nodes"][0]["openapi_spec"] == ""

    def test_tcp_node_no_openapi_spec(self):
        raw = {
            "version": 1,
            "nodes": [{"name": "db", "port": 5432, "proxy_mode": "tcp"}],
        }
        result = migrate_v1_to_v2(raw)
        assert "openapi_spec" not in result["nodes"][0]

    def test_grpc_node_no_openapi_spec(self):
        raw = {
            "version": 1,
            "nodes": [{"name": "rpc", "port": 9090, "proxy_mode": "grpc"}],
        }
        result = migrate_v1_to_v2(raw)
        assert "openapi_spec" not in result["nodes"][0]

    def test_edge_gets_data_tiers_in_flight(self):
        raw = {
            "version": 1,
            "nodes": [
                {"name": "api", "port": 8001},
                {"name": "db", "port": 5432},
            ],
            "edges": [{"source": "api", "target": "db"}],
        }
        result = migrate_v1_to_v2(raw)
        assert result["edges"][0]["data_tiers_in_flight"] == []

    def test_arbiter_stub_added(self):
        result = migrate_v1_to_v2({"version": 1})
        assert "arbiter" in result
        assert result["arbiter"]["endpoint"] == ""
        assert result["arbiter"]["api_endpoint"] == ""

    def test_ledger_stub_added(self):
        result = migrate_v1_to_v2({"version": 1})
        assert "ledger" in result
        assert result["ledger"]["api_endpoint"] == ""

    def test_audit_channel_stub_added(self):
        result = migrate_v1_to_v2({"version": 1})
        assert "audit_channel" in result
        assert result["audit_channel"]["port"] == 9000
        assert result["audit_channel"]["protocol"] == "http"

    def test_preserves_existing_fields(self):
        raw = {
            "version": 1,
            "name": "myproject",
            "nodes": [
                {
                    "name": "api",
                    "port": 8001,
                    "contract": "specs/api.yaml",
                    "role": "ingress",
                    "metadata": {"team": "platform"},
                }
            ],
            "edges": [{"source": "api", "target": "api", "label": "self"}],
        }
        # Note: the self-loop edge won't validate in Pydantic but we test
        # raw dict migration only here
        result = migrate_v1_to_v2(raw)
        node = result["nodes"][0]
        assert node["name"] == "api"
        assert node["contract"] == "specs/api.yaml"
        assert node["role"] == "ingress"
        assert node["metadata"] == {"team": "platform"}

    def test_does_not_overwrite_existing_v2_fields(self):
        raw = {
            "version": 1,
            "nodes": [
                {
                    "name": "api",
                    "port": 8001,
                    "data_access": {"reads": ["PII"], "writes": ["PII"]},
                    "authority": ["user.*"],
                    "openapi_spec": "specs/api.yaml",
                }
            ],
            "edges": [
                {
                    "source": "api",
                    "target": "db",
                    "data_tiers_in_flight": ["FINANCIAL"],
                }
            ],
            "arbiter": {"api_endpoint": "http://localhost:7700"},
        }
        result = migrate_v1_to_v2(raw)
        node = result["nodes"][0]
        assert node["data_access"] == {"reads": ["PII"], "writes": ["PII"]}
        assert node["authority"] == ["user.*"]
        assert node["openapi_spec"] == "specs/api.yaml"
        assert result["edges"][0]["data_tiers_in_flight"] == ["FINANCIAL"]
        assert result["arbiter"]["api_endpoint"] == "http://localhost:7700"

    def test_empty_nodes_list(self):
        raw = {"version": 1, "nodes": []}
        result = migrate_v1_to_v2(raw)
        assert result["version"] == 2
        assert result["nodes"] == []

    def test_no_nodes_key(self):
        raw = {"version": 1, "name": "empty"}
        result = migrate_v1_to_v2(raw)
        assert result["version"] == 2
        assert "arbiter" in result

    def test_no_edges_key(self):
        raw = {"version": 1}
        result = migrate_v1_to_v2(raw)
        assert result["version"] == 2
        assert "ledger" in result

    def test_does_not_mutate_input(self):
        raw = {
            "version": 1,
            "nodes": [{"name": "api", "port": 8001}],
        }
        import copy
        original = copy.deepcopy(raw)
        migrate_v1_to_v2(raw)
        assert raw == original

    def test_all_v2_fields_present_after_migration(self):
        """Full integration check: every v2 field is present."""
        raw = {
            "version": 1,
            "name": "full",
            "nodes": [
                {"name": "gateway", "port": 8001, "role": "ingress"},
                {"name": "api", "port": 8002},
                {"name": "db", "port": 5432, "proxy_mode": "tcp", "role": "egress"},
            ],
            "edges": [
                {"source": "gateway", "target": "api"},
                {"source": "api", "target": "db"},
            ],
        }
        result = migrate_v1_to_v2(raw)

        assert result["version"] == 2

        for node in result["nodes"]:
            assert "data_access" in node
            assert "authority" in node
            if node.get("proxy_mode", "http") == "http":
                assert "openapi_spec" in node

        for edge in result["edges"]:
            assert "data_tiers_in_flight" in edge

        assert "arbiter" in result
        assert "ledger" in result
        assert "audit_channel" in result


# -- Integration tests via run_migrate --


class TestRunMigrate:
    def _write_v1(self, path: Path, extra: dict | None = None) -> Path:
        data: dict = {
            "name": "test",
            "version": 1,
            "nodes": [
                {"name": "api", "port": 8001},
                {"name": "db", "port": 5432, "proxy_mode": "tcp"},
            ],
            "edges": [{"source": "api", "target": "db"}],
        }
        if extra:
            data.update(extra)
        cfg = path / "baton.yaml"
        cfg.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        return cfg

    def test_v1_upgraded_to_v2(self, project_dir: Path):
        cfg = self._write_v1(project_dir)
        rc = run_migrate(cfg)
        assert rc == 0

        with open(cfg) as f:
            result = yaml.safe_load(f)
        assert result["version"] == 2
        assert result["nodes"][0]["data_access"] == {"reads": [], "writes": []}
        assert result["nodes"][0]["authority"] == []
        assert result["nodes"][0]["openapi_spec"] == ""
        # TCP node should not have openapi_spec
        assert "openapi_spec" not in result["nodes"][1]
        assert result["edges"][0]["data_tiers_in_flight"] == []
        assert "arbiter" in result
        assert "ledger" in result
        assert "audit_channel" in result

    def test_v2_unchanged(self, project_dir: Path):
        data = {"name": "test", "version": 2, "nodes": [{"name": "api", "port": 8001}]}
        cfg = project_dir / "baton.yaml"
        cfg.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

        rc = run_migrate(cfg)
        assert rc == 0

        with open(cfg) as f:
            result = yaml.safe_load(f)
        # Should be untouched
        assert result == data

    def test_dry_run_no_write(self, project_dir: Path, capsys):
        cfg = self._write_v1(project_dir)
        original = cfg.read_text()

        rc = run_migrate(cfg, dry_run=True)
        assert rc == 0

        # File should be unchanged
        assert cfg.read_text() == original

        # Migrated YAML should be printed to stdout
        captured = capsys.readouterr()
        assert "version: 2" in captured.out

    def test_output_to_different_file(self, project_dir: Path):
        cfg = self._write_v1(project_dir)
        out = project_dir / "baton-v2.yaml"

        rc = run_migrate(cfg, output_path=out)
        assert rc == 0
        assert out.exists()

        with open(out) as f:
            result = yaml.safe_load(f)
        assert result["version"] == 2

        # Original should still be v1
        with open(cfg) as f:
            original = yaml.safe_load(f)
        assert original["version"] == 1

    def test_missing_file(self, project_dir: Path):
        rc = run_migrate(project_dir / "nonexistent.yaml")
        assert rc == 1

    def test_missing_version_field(self, project_dir: Path):
        """Config with no version field should be treated as v1."""
        data = {"name": "legacy", "nodes": [{"name": "api", "port": 8001}]}
        cfg = project_dir / "baton.yaml"
        cfg.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

        rc = run_migrate(cfg)
        assert rc == 0

        with open(cfg) as f:
            result = yaml.safe_load(f)
        assert result["version"] == 2
        assert result["nodes"][0]["data_access"] == {"reads": [], "writes": []}

    def test_empty_yaml(self, project_dir: Path):
        cfg = project_dir / "baton.yaml"
        cfg.write_text("")

        rc = run_migrate(cfg)
        assert rc == 0

        with open(cfg) as f:
            result = yaml.safe_load(f)
        assert result["version"] == 2

    def test_empty_nodes(self, project_dir: Path):
        data = {"version": 1, "nodes": [], "edges": []}
        cfg = project_dir / "baton.yaml"
        cfg.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

        rc = run_migrate(cfg)
        assert rc == 0

        with open(cfg) as f:
            result = yaml.safe_load(f)
        assert result["version"] == 2
        assert result["nodes"] == []
        assert result["edges"] == []


# -- CLI integration --


class TestCLIMigrateConfig:
    def test_cli_migrate(self, project_dir: Path, monkeypatch):
        from baton.cli import main

        data = {
            "name": "test",
            "version": 1,
            "nodes": [{"name": "api", "port": 8001}],
        }
        cfg = project_dir / "baton.yaml"
        cfg.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

        rc = main(["migrate-config", "--config", str(cfg)])
        assert rc == 0

        with open(cfg) as f:
            result = yaml.safe_load(f)
        assert result["version"] == 2

    def test_cli_dry_run(self, project_dir: Path, capsys):
        from baton.cli import main

        data = {"name": "test", "version": 1, "nodes": []}
        cfg = project_dir / "baton.yaml"
        cfg.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

        original = cfg.read_text()
        rc = main(["migrate-config", "--config", str(cfg), "--dry-run"])
        assert rc == 0
        assert cfg.read_text() == original

    def test_cli_output(self, project_dir: Path):
        from baton.cli import main

        data = {"name": "test", "version": 1, "nodes": []}
        cfg = project_dir / "baton.yaml"
        cfg.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

        out = project_dir / "output.yaml"
        rc = main(["migrate-config", "--config", str(cfg), "--output", str(out)])
        assert rc == 0
        assert out.exists()

    def test_cli_already_v2(self, project_dir: Path, capsys):
        from baton.cli import main

        data = {"name": "test", "version": 2}
        cfg = project_dir / "baton.yaml"
        cfg.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

        rc = main(["migrate-config", "--config", str(cfg)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Already at v2" in captured.out
