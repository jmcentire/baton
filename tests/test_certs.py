"""Tests for baton.certs -- certificate monitoring and rotation."""

from __future__ import annotations

import ssl
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Self-signed cert generation fixture
# ---------------------------------------------------------------------------


def _generate_self_signed(
    tmp_path: Path,
    cn: str = "test.baton.local",
    days: int = 365,
) -> tuple[Path, Path]:
    """Generate a self-signed cert + key in tmp_path.

    Returns (cert_path, key_path).
    Requires the 'cryptography' package.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from datetime import datetime, timedelta, timezone

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=days))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(cn)]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )

    return cert_path, key_path


try:
    import cryptography  # noqa: F401
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

pytestmark = pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography package not installed")


# ---------------------------------------------------------------------------
# parse_certificate tests
# ---------------------------------------------------------------------------


class TestParseCertificate:
    def test_parse_valid_cert(self, tmp_path):
        from baton.certs import parse_certificate

        cert_path, _ = _generate_self_signed(tmp_path)
        info = parse_certificate(cert_path)

        assert "test.baton.local" in info.subject
        assert info.days_until_expiry > 360
        assert info.fingerprint_sha256 != ""
        assert "test.baton.local" in info.san
        assert not info.is_expired

    def test_parse_missing_cert(self, tmp_path):
        from baton.certs import parse_certificate

        with pytest.raises(FileNotFoundError):
            parse_certificate(tmp_path / "nonexistent.pem")

    def test_expired_cert(self, tmp_path):
        from baton.certs import parse_certificate

        cert_path, _ = _generate_self_signed(tmp_path, days=0)
        info = parse_certificate(cert_path)
        assert info.days_until_expiry <= 0


# ---------------------------------------------------------------------------
# CertificateMonitor tests
# ---------------------------------------------------------------------------


class TestCertificateMonitor:
    def test_initial_load(self, tmp_path):
        from baton.certs import CertificateMonitor

        cert_path, _ = _generate_self_signed(tmp_path)
        monitor = CertificateMonitor(cert_path)

        info, events = monitor.check()
        assert info is not None
        assert any(e.event_type == "loaded" for e in events)

    def test_missing_cert_error(self, tmp_path):
        from baton.certs import CertificateMonitor

        monitor = CertificateMonitor(tmp_path / "missing.pem")
        info, events = monitor.check()
        assert info is None
        assert any(e.event_type == "error" for e in events)

    def test_expiring_warning(self, tmp_path):
        from baton.certs import CertificateMonitor

        cert_path, _ = _generate_self_signed(tmp_path, days=15)
        monitor = CertificateMonitor(cert_path, warning_days=30, critical_days=7)

        info, events = monitor.check()
        assert any(e.event_type == "expiring_warning" for e in events)

    def test_expiring_critical(self, tmp_path):
        from baton.certs import CertificateMonitor

        cert_path, _ = _generate_self_signed(tmp_path, days=3)
        monitor = CertificateMonitor(cert_path, warning_days=30, critical_days=7)

        info, events = monitor.check()
        assert any(e.event_type == "expiring_critical" for e in events)

    def test_file_change_detected(self, tmp_path):
        from baton.certs import CertificateMonitor

        cert_path, _ = _generate_self_signed(tmp_path)
        monitor = CertificateMonitor(cert_path)

        # First check
        monitor.check()

        # Regenerate cert (changes mtime)
        time.sleep(0.01)
        _generate_self_signed(tmp_path, cn="new.baton.local")

        # Second check
        info, events = monitor.check()
        assert any(e.event_type == "rotated" for e in events)


# ---------------------------------------------------------------------------
# CertificateRotator tests
# ---------------------------------------------------------------------------


class TestCertificateRotator:
    def test_rotate_success(self, tmp_path):
        from baton.certs import CertificateRotator

        cert_path, key_path = _generate_self_signed(tmp_path)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_path), str(key_path))

        rotator = CertificateRotator(ctx, cert_path, key_path)
        assert rotator.rotate() is True

    def test_rotate_bad_key(self, tmp_path):
        from baton.certs import CertificateRotator

        cert_path, key_path = _generate_self_signed(tmp_path)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_path), str(key_path))

        # Corrupt the key file
        bad_key = tmp_path / "bad_key.pem"
        bad_key.write_text("not a key")

        rotator = CertificateRotator(ctx, cert_path, bad_key)
        assert rotator.rotate() is False


# ---------------------------------------------------------------------------
# CertificateManager tests
# ---------------------------------------------------------------------------


class TestCertificateManager:
    def test_check_now(self, tmp_path):
        from baton.certs import CertificateManager

        cert_path, key_path = _generate_self_signed(tmp_path)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_path), str(key_path))

        mgr = CertificateManager(ctx, cert_path, key_path)
        info, events = mgr.check_now()
        assert info is not None
        assert len(events) >= 1

    def test_auto_rotate_on_change(self, tmp_path):
        from baton.certs import CertificateManager

        cert_path, key_path = _generate_self_signed(tmp_path)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_path), str(key_path))

        mgr = CertificateManager(ctx, cert_path, key_path)

        # First check loads cert
        mgr.check_now()

        # Regenerate cert
        time.sleep(0.01)
        _generate_self_signed(tmp_path, cn="rotated.baton.local")

        # Second check should detect change and rotate
        info, events = mgr.check_now()
        event_types = [e.event_type for e in events]
        assert "rotated" in event_types

    def test_events_accumulated(self, tmp_path):
        from baton.certs import CertificateManager

        cert_path, key_path = _generate_self_signed(tmp_path)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_path), str(key_path))

        mgr = CertificateManager(ctx, cert_path, key_path)
        mgr.check_now()
        mgr.check_now()

        assert len(mgr.events) >= 1

    async def test_run_and_stop(self, tmp_path):
        from baton.certs import CertificateManager
        import asyncio

        cert_path, key_path = _generate_self_signed(tmp_path)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_path), str(key_path))

        mgr = CertificateManager(ctx, cert_path, key_path, check_interval=0.1)

        task = asyncio.create_task(mgr.run())
        await asyncio.sleep(0.3)
        assert mgr.is_running

        mgr.stop()
        await asyncio.sleep(0.2)
        assert not mgr.is_running

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# CertificateInfo tests
# ---------------------------------------------------------------------------


class TestCertificateInfo:
    def test_is_expired_true(self):
        from baton.certs import CertificateInfo

        info = CertificateInfo(days_until_expiry=0)
        assert info.is_expired

    def test_is_expired_false(self):
        from baton.certs import CertificateInfo

        info = CertificateInfo(days_until_expiry=30)
        assert not info.is_expired

    def test_is_expired_unknown(self):
        from baton.certs import CertificateInfo

        info = CertificateInfo(days_until_expiry=-1)
        assert not info.is_expired
