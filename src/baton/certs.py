"""Certificate monitoring and rotation for Baton.

Watches certificate files and hot-reloads them into an existing SSLContext
when they change. New connections get the new cert; existing connections
are unaffected (zero-downtime rotation).

Requires the 'cryptography' package for cert parsing.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CertificateInfo:
    """Parsed certificate metadata."""

    subject: str = ""
    issuer: str = ""
    not_before: str = ""
    not_after: str = ""
    serial_number: str = ""
    san: list[str] = field(default_factory=list)
    fingerprint_sha256: str = ""
    days_until_expiry: int = -1

    @property
    def is_expired(self) -> bool:
        return self.days_until_expiry <= 0 and self.days_until_expiry != -1


@dataclass
class CertificateEvent:
    """Certificate lifecycle event."""

    event_type: str  # "loaded", "expiring_warning", "expiring_critical", "rotated", "error"
    cert_path: str
    detail: str = ""
    timestamp: str = ""


def parse_certificate(cert_path: str | Path) -> CertificateInfo:
    """Parse a PEM certificate file and extract metadata.

    Falls back to basic info if cryptography package is not available.
    """
    path = Path(cert_path)
    if not path.exists():
        raise FileNotFoundError(f"Certificate not found: {cert_path}")

    pem_data = path.read_bytes()

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes

        cert = x509.load_pem_x509_certificate(pem_data)

        # Extract SAN
        san: list[str] = []
        try:
            san_ext = cert.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            )
            san = list(san_ext.value.get_values_for_type(x509.DNSName))
        except x509.ExtensionNotFound:
            pass

        now = datetime.now(timezone.utc)
        days_until = (cert.not_valid_after_utc - now).days

        fingerprint = cert.fingerprint(hashes.SHA256()).hex()

        return CertificateInfo(
            subject=cert.subject.rfc4514_string(),
            issuer=cert.issuer.rfc4514_string(),
            not_before=cert.not_valid_before_utc.isoformat(),
            not_after=cert.not_valid_after_utc.isoformat(),
            serial_number=str(cert.serial_number),
            san=san,
            fingerprint_sha256=fingerprint,
            days_until_expiry=days_until,
        )
    except ImportError:
        # Fallback: parse PEM manually for basic info
        logger.debug("cryptography package not available, using basic cert parsing")
        return CertificateInfo(
            subject="(cryptography package required for details)",
            fingerprint_sha256="",
        )


class CertificateMonitor:
    """Monitors certificate files for expiry and changes."""

    def __init__(
        self,
        cert_path: str | Path,
        warning_days: int = 30,
        critical_days: int = 7,
    ):
        self._cert_path = Path(cert_path)
        self._warning_days = warning_days
        self._critical_days = critical_days
        self._last_mtime: float = 0.0
        self._last_fingerprint: str = ""

    @property
    def cert_path(self) -> Path:
        return self._cert_path

    def check(self) -> tuple[CertificateInfo | None, list[CertificateEvent]]:
        """Check the certificate. Returns (info, events).

        Events may include expiry warnings or file change notifications.
        """
        events: list[CertificateEvent] = []

        if not self._cert_path.exists():
            events.append(CertificateEvent(
                event_type="error",
                cert_path=str(self._cert_path),
                detail="Certificate file not found",
                timestamp=_now_iso(),
            ))
            return None, events

        try:
            info = parse_certificate(self._cert_path)
        except Exception as e:
            events.append(CertificateEvent(
                event_type="error",
                cert_path=str(self._cert_path),
                detail=f"Failed to parse certificate: {e}",
                timestamp=_now_iso(),
            ))
            return None, events

        # Check for file change
        mtime = self._cert_path.stat().st_mtime
        if self._last_mtime > 0 and mtime != self._last_mtime:
            events.append(CertificateEvent(
                event_type="rotated",
                cert_path=str(self._cert_path),
                detail=f"Certificate file changed (fingerprint: {info.fingerprint_sha256[:16]}...)",
                timestamp=_now_iso(),
            ))
        self._last_mtime = mtime

        # Expiry warnings
        if info.days_until_expiry >= 0:
            if info.days_until_expiry <= self._critical_days:
                events.append(CertificateEvent(
                    event_type="expiring_critical",
                    cert_path=str(self._cert_path),
                    detail=f"Certificate expires in {info.days_until_expiry} days",
                    timestamp=_now_iso(),
                ))
            elif info.days_until_expiry <= self._warning_days:
                events.append(CertificateEvent(
                    event_type="expiring_warning",
                    cert_path=str(self._cert_path),
                    detail=f"Certificate expires in {info.days_until_expiry} days",
                    timestamp=_now_iso(),
                ))

        if not events and self._last_fingerprint == "":
            events.append(CertificateEvent(
                event_type="loaded",
                cert_path=str(self._cert_path),
                detail=f"Certificate loaded (expires in {info.days_until_expiry} days)",
                timestamp=_now_iso(),
            ))

        self._last_fingerprint = info.fingerprint_sha256
        return info, events


class CertificateRotator:
    """Hot-reloads certificates into an existing SSLContext."""

    def __init__(self, ssl_context: ssl.SSLContext, cert_path: str | Path, key_path: str | Path):
        self._ssl_context = ssl_context
        self._cert_path = Path(cert_path)
        self._key_path = Path(key_path)

    def rotate(self) -> bool:
        """Reload the certificate into the SSLContext.

        Returns True if reload succeeded, False otherwise.
        New connections will use the new cert. Existing connections are unaffected.
        """
        try:
            self._ssl_context.load_cert_chain(
                str(self._cert_path), str(self._key_path)
            )
            logger.info(f"Certificate rotated: {self._cert_path}")
            return True
        except Exception as e:
            logger.error(f"Certificate rotation failed: {e}")
            return False


class CertificateManager:
    """Orchestrates certificate monitoring and rotation.

    Periodically checks the certificate file and reloads it into the
    SSLContext when it changes or is approaching expiry.
    """

    def __init__(
        self,
        ssl_context: ssl.SSLContext,
        cert_path: str | Path,
        key_path: str | Path,
        check_interval: float = 3600.0,  # 1 hour
        warning_days: int = 30,
        critical_days: int = 7,
    ):
        self._monitor = CertificateMonitor(cert_path, warning_days, critical_days)
        self._rotator = CertificateRotator(ssl_context, cert_path, key_path)
        self._check_interval = check_interval
        self._running = False
        self._events: list[CertificateEvent] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def events(self) -> list[CertificateEvent]:
        return list(self._events)

    @property
    def monitor(self) -> CertificateMonitor:
        return self._monitor

    def check_now(self) -> tuple[CertificateInfo | None, list[CertificateEvent]]:
        """Perform an immediate check and rotation if needed."""
        info, events = self._monitor.check()

        # If cert file changed, rotate it
        for evt in events:
            if evt.event_type == "rotated":
                success = self._rotator.rotate()
                if not success:
                    events.append(CertificateEvent(
                        event_type="error",
                        cert_path=str(self._monitor.cert_path),
                        detail="Rotation failed after file change",
                        timestamp=_now_iso(),
                    ))

        self._events.extend(events)
        return info, events

    async def run(self) -> None:
        """Async loop: check certificate at regular intervals."""
        self._running = True
        try:
            while self._running:
                self.check_now()
                await asyncio.sleep(self._check_interval)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    def stop(self) -> None:
        """Signal the run loop to stop."""
        self._running = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
