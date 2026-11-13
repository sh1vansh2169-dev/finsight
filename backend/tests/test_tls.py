"""The phone app's HTTPS certificates (made in a temporary folder)."""

import ipaddress
import ssl
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec

from moneyos import tls


def load(path):
    return x509.load_pem_x509_certificate(path.read_bytes())


def test_the_server_certificate_is_signed_by_the_local_ca_and_names_the_addresses(tmp_path):
    cert_path, key_path = tls.ensure_server_cert(tmp_path, ["192.168.1.20"])
    ca, cert = load(tmp_path / "ca.pem"), load(cert_path)
    assert cert.issuer == ca.subject
    ca.public_key().verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm))
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert {str(i) for i in san.get_values_for_type(x509.IPAddress)} == {"127.0.0.1", "192.168.1.20"}
    assert san.get_values_for_type(x509.DNSName) == ["localhost"]
    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True
    assert cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is False
    assert cert.not_valid_after_utc - cert.not_valid_before_utc <= timedelta(days=398)  # phones' limit
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(cert_path, key_path)  # a real TLS server can use the pair


def test_a_new_address_gets_a_new_certificate_from_the_same_ca(tmp_path):
    first, _ = tls.ensure_server_cert(tmp_path, ["192.168.1.20"])
    ca_before = (tmp_path / "ca.pem").read_bytes()
    serial = load(first).serial_number
    same, _ = tls.ensure_server_cert(tmp_path, ["192.168.1.20"])
    assert load(same).serial_number == serial  # nothing changed: kept
    moved, _ = tls.ensure_server_cert(tmp_path, ["192.168.1.35"])
    assert load(moved).serial_number != serial
    assert (tmp_path / "ca.pem").read_bytes() == ca_before  # the app keeps trusting it


def test_a_certificate_near_expiry_is_renewed(tmp_path):
    long_ago = datetime.now(UTC) - timedelta(days=380)
    old, _ = tls.ensure_server_cert(tmp_path, ["10.0.0.5"], now=long_ago)
    serial = load(old).serial_number
    renewed, _ = tls.ensure_server_cert(tmp_path, ["10.0.0.5"])
    assert load(renewed).serial_number != serial


def test_lan_addresses_are_plain_ipv4_and_not_loopback():
    for address in tls.lan_addresses():
        ip = ipaddress.ip_address(address)
        assert ip.version == 4 and not ip.is_loopback and not ip.is_link_local


def test_a_client_trusting_only_the_ca_completes_a_verified_handshake(tmp_path):
    """A real TLS connection, verified the strict way modern clients (and phones) do."""
    import socket
    import threading

    cert_path, key_path = tls.ensure_server_cert(tmp_path, [])
    server_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_ctx.load_cert_chain(cert_path, key_path)
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def serve():
        conn, _ = listener.accept()
        try:
            with server_ctx.wrap_socket(conn, server_side=True) as tls_conn:
                tls_conn.sendall(b"ok")
        except ssl.SSLError:
            pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    client_ctx = ssl.create_default_context(cafile=str(tmp_path / "ca.pem"))
    client_ctx.verify_flags |= ssl.VERIFY_X509_STRICT
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with client_ctx.wrap_socket(raw, server_hostname="127.0.0.1") as tls_conn:
                assert tls_conn.recv(2) == b"ok"
    finally:
        listener.close()
        thread.join(5)


def test_certificates_from_before_the_fix_are_replaced(tmp_path):
    """Earlier certificates had no key identifiers, which strict clients reject."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FinSight local CA")])
    now = datetime.now(UTC)
    old_ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
              .serial_number(1).not_valid_before(now).not_valid_after(now + timedelta(days=10))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).sign(key, hashes.SHA256()))
    (tmp_path / "ca.pem").write_bytes(old_ca.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "ca.key").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                        serialization.NoEncryption()))
    cert_path, _ = tls.ensure_server_cert(tmp_path, [])
    new_ca = load(tmp_path / "ca.pem")
    assert new_ca.serial_number != 1
    new_ca.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)
    load(cert_path).verify_directly_issued_by(new_ca)
