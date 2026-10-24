"""Bounded Alexa HTTPS request verification; no bearer HA token is exposed."""

from __future__ import annotations

import base64
import posixpath
import ssl
from datetime import UTC, datetime
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.verification import PolicyBuilder, Store


class AlexaSecurityError(ValueError):
    """A deliberately generic rejection without request data or certificates."""


def certificate_url(value):
    """Allow only Amazon's signing-certificate location, without redirects."""
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "s3.amazonaws.com"
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "%" in parsed.path
            or "\\" in parsed.path
            or not posixpath.normpath(parsed.path).startswith("/echo.api/")
            or not parsed.path.endswith(".pem")
        ):
            raise ValueError
    except (TypeError, ValueError):
        raise AlexaSecurityError("Invalid signing certificate URL.") from None
    return value


def timestamp_valid(envelope):
    try:
        timestamp = datetime.fromisoformat(envelope["request"]["timestamp"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or abs((datetime.now(UTC) - timestamp).total_seconds()) > 150:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AlexaSecurityError("Invalid request timestamp.") from None


def trusted_signer(pem):
    """Run certificate parsing, system-root loading and chain validation off-loop."""
    try:
        chain = x509.load_pem_x509_certificates(pem)
        roots = [
            x509.load_der_x509_certificate(item) for item in ssl.create_default_context().get_ca_certs(True)
        ]
        now = datetime.now(UTC)
        verifier = (
            PolicyBuilder()
            .store(Store(roots))
            .time(now)
            .build_server_verifier(x509.DNSName("echo-api.amazon.com"))
        )
        verifier.verify(chain[0], chain[1:])
        key = chain[0].public_key()
        if not isinstance(key, rsa.RSAPublicKey):
            raise ValueError
        return chain[0]
    except Exception:
        raise AlexaSecurityError("Invalid signing certificate.") from None


def verify_signature(signer, signature, body):
    try:
        now = datetime.now(UTC)
        if not signer.not_valid_before_utc <= now <= signer.not_valid_after_utc:
            raise ValueError
        signer.public_key().verify(
            base64.b64decode(signature, validate=True), body, padding.PKCS1v15(), hashes.SHA256()
        )
    except Exception:
        raise AlexaSecurityError("Invalid request signature.") from None
