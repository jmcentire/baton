"""Tests for baton.certs using injected metadata and reload outcomes only."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from baton.certs import (
    CertificateInfo,
    CertificateManager,
    CertificateMonitor,
    CertificateRotator,
    parse_certificate,
)


def _certificate_reference(tmp_path: Path) -> Path:
    path = tmp_path / "certificate.ref"
    path.touch()
    return path


def _info(days: int = 365, subject: str = "CN=service.baton.local") -> CertificateInfo:
    return CertificateInfo(
        subject=subject,
        san=["service.baton.local"],
        fingerprint_sha256="fingerprint-reference",
        days_until_expiry=days,
    )


def _parser(info: CertificateInfo):
    def parse(_path: str | Path) -> CertificateInfo:
        return info

    return parse


class ReloadRecorder:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def __call__(self, certificate_path: str, custody_reference: str) -> None:
        self.calls.append((certificate_path, custody_reference))
        if self.fail:
            raise RuntimeError("reload unavailable")


class TestParseCertificate:
    def test_parse_missing_certificate(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_certificate(tmp_path / "nonexistent.pem")


class TestCertificateMonitor:
    def test_initial_load(self, tmp_path):
        certificate_ref = _certificate_reference(tmp_path)
        monitor = CertificateMonitor(certificate_ref, parser=_parser(_info()))

        info, events = monitor.check()
        assert info is not None
        assert info.subject == "CN=service.baton.local"
        assert any(event.event_type == "loaded" for event in events)

    def test_missing_certificate_error(self, tmp_path):
        monitor = CertificateMonitor(tmp_path / "missing.ref", parser=_parser(_info()))
        info, events = monitor.check()

        assert info is None
        assert any(event.event_type == "error" for event in events)

    def test_expiring_warning(self, tmp_path):
        certificate_ref = _certificate_reference(tmp_path)
        monitor = CertificateMonitor(
            certificate_ref,
            warning_days=30,
            critical_days=7,
            parser=_parser(_info(days=15)),
        )

        _info_result, events = monitor.check()
        assert any(event.event_type == "expiring_warning" for event in events)

    def test_expiring_critical(self, tmp_path):
        certificate_ref = _certificate_reference(tmp_path)
        monitor = CertificateMonitor(
            certificate_ref,
            warning_days=30,
            critical_days=7,
            parser=_parser(_info(days=3)),
        )

        _info_result, events = monitor.check()
        assert any(event.event_type == "expiring_critical" for event in events)

    def test_file_change_detected(self, tmp_path):
        certificate_ref = _certificate_reference(tmp_path)
        monitor = CertificateMonitor(certificate_ref, parser=_parser(_info()))
        monitor.check()

        time.sleep(0.01)
        certificate_ref.write_text("updated-reference")

        _info_result, events = monitor.check()
        assert any(event.event_type == "rotated" for event in events)


class TestCertificateRotator:
    def test_rotate_success(self, tmp_path):
        certificate_ref = _certificate_reference(tmp_path)
        reload = ReloadRecorder()
        rotator = CertificateRotator(
            object(),
            certificate_ref,
            tmp_path / "custody-reference",
            certificate_loader=reload,
        )

        assert rotator.rotate() is True
        assert len(reload.calls) == 1

    def test_rotate_failed_reload(self, tmp_path):
        certificate_ref = _certificate_reference(tmp_path)
        rotator = CertificateRotator(
            object(),
            certificate_ref,
            tmp_path / "custody-reference",
            certificate_loader=ReloadRecorder(fail=True),
        )

        assert rotator.rotate() is False


class TestCertificateManager:
    def _manager(self, tmp_path, *, interval: float = 3600.0):
        certificate_ref = _certificate_reference(tmp_path)
        reload = ReloadRecorder()
        manager = CertificateManager(
            object(),
            certificate_ref,
            tmp_path / "custody-reference",
            check_interval=interval,
            parser=_parser(_info()),
            certificate_loader=reload,
        )
        return manager, certificate_ref, reload

    def test_check_now(self, tmp_path):
        manager, _certificate_ref, _reload = self._manager(tmp_path)
        info, events = manager.check_now()

        assert info is not None
        assert len(events) >= 1

    def test_auto_rotate_on_change(self, tmp_path):
        manager, certificate_ref, reload = self._manager(tmp_path)
        manager.check_now()

        time.sleep(0.01)
        certificate_ref.write_text("updated-reference")
        _info_result, events = manager.check_now()

        assert "rotated" in [event.event_type for event in events]
        assert len(reload.calls) == 1

    def test_events_accumulated(self, tmp_path):
        manager, _certificate_ref, _reload = self._manager(tmp_path)
        manager.check_now()
        manager.check_now()

        assert len(manager.events) >= 1

    async def test_run_and_stop(self, tmp_path):
        manager, _certificate_ref, _reload = self._manager(tmp_path, interval=0.01)

        task = asyncio.create_task(manager.run())
        await asyncio.sleep(0.03)
        assert manager.is_running

        manager.stop()
        await asyncio.sleep(0.02)
        assert not manager.is_running

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestCertificateInfo:
    def test_is_expired_true(self):
        info = CertificateInfo(days_until_expiry=0)
        assert info.is_expired

    def test_is_expired_false(self):
        info = CertificateInfo(days_until_expiry=30)
        assert not info.is_expired

    def test_is_expired_unknown(self):
        info = CertificateInfo(days_until_expiry=-1)
        assert not info.is_expired
