"""HTTPS for the phone app on the home network.

FinSight makes its own small certificate authority (CA) on this computer
and uses it to sign the server's certificate. The phone app is built to
trust that CA and nothing else for FinSight, so another device on the Wi-Fi
cannot pretend to be FinSight. When this computer's network address changes,
a new server certificate is signed by the same CA, so the app keeps working
without being rebuilt.

Files (in ``data/tls``, git-ignored): ``ca.pem`` (public, goes into the app),
``ca.key`` (private, never leaves this computer), ``server.pem``, ``server.key``.
"""

from __future__ import annotations

import ipaddress
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_DAYS = 3650
SERVER_DAYS = 397  # the longest phones accept for a server certificate
RENEW_BEFORE = timedelta(days=30)


def lan_addresses() -> list[str]:
    """This computer's IPv4 addresses on its networks (not 127.x)."""
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    try:  # the address used to reach the internet; no packet is sent
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            found.add(probe.getsockname()[0])
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith("127.") and not a.startswith("169.254."))


def _write_key(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _load(cert_path: Path, key_path: Path):
    return (x509.load_pem_x509_certificate(cert_path.read_bytes()),
            serialization.load_pem_private_key(key_path.read_bytes(), password=None))


def ensure_ca(folder: Path, now: datetime | None = None) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    folder.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = folder / "ca.pem", folder / "ca.key"
    if cert_path.exists() and key_path.exists():
        cert, key = _load(cert_path, key_path)
        if _has(cert, x509.SubjectKeyIdentifier):
            return cert, key
        # Made by an earlier version without key identifiers, which strict clients reject.
    now = now or datetime.now(UTC)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FinSight local CA")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=CA_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                         crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    _write_key(key_path, key)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert, key


def _has(cert: x509.Certificate, extension) -> bool:
    try:
        cert.extensions.get_extension_for_class(extension)
        return True
    except x509.ExtensionNotFound:
        return False


def _signed_by(cert: x509.Certificate, ca: x509.Certificate) -> bool:
    try:
        cert.verify_directly_issued_by(ca)
        return True
    except (ValueError, TypeError, Exception):  # a different CA (it was replaced): re-issue
        return False


def _covers(cert: x509.Certificate, ips: list[str], now: datetime) -> bool:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return False
    have = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    return set(ips) <= have and cert.not_valid_after_utc - RENEW_BEFORE > now


def ensure_server_cert(folder: Path, ips: list[str], now: datetime | None = None) -> tuple[Path, Path]:
    """A server certificate for localhost and ``ips``, signed by the CA; renewed when the
    addresses change or it is about to expire. Returns (certificate path, key path)."""
    now = now or datetime.now(UTC)
    ca_cert, ca_key = ensure_ca(folder, now)
    cert_path, key_path = folder / "server.pem", folder / "server.key"
    wanted = sorted({"127.0.0.1", *ips})
    if cert_path.exists() and key_path.exists():
        current, _ = _load(cert_path, key_path)
        if (_covers(current, wanted, now) and current.issuer == ca_cert.subject
                and _has(current, x509.AuthorityKeyIdentifier) and _signed_by(current, ca_cert)):
            return cert_path, key_path
    key = ec.generate_private_key(ec.SECP256R1())
    names = [x509.DNSName("localhost"), *(x509.IPAddress(ipaddress.ip_address(ip)) for ip in wanted)]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FinSight")]))
            .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=SERVER_DAYS))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write_key(key_path, key)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def fingerprint(cert_path: Path) -> str:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return cert.fingerprint(hashes.SHA256()).hex(":").upper()
