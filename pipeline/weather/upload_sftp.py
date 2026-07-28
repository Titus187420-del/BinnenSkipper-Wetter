#!/usr/bin/env python3
"""Upload the built weather / storm-light JSON to the Strato webspace via SFTP.

Uses paramiko (the same kind of native SFTP-over-SSH library WinSCP / FileZilla
use) with plain password authentication. This deliberately avoids the external
``ssh`` + ``sshpass`` combination: OpenSSH's ``sftp -b`` runs with BatchMode,
which suppresses the password prompt, so sshpass never gets to answer it and the
login fails with "Permission denied" even when the password is correct. paramiko
sends the password directly, exactly like WinSCP, and gives an explicit error.

Credentials come from environment variables (GitHub Actions secrets). Values are
stripped of stray whitespace / CR that easily sneaks into copy-pasted secrets
(a leading space in the user makes the server drop us; one in the password gives
"Permission denied"). Only lengths are logged, never the values.

Environment:
  FTP_HOST         SFTP host (e.g. DEINEKENNUNG.ssh.w1.strato.hosting)   [required]
  FTP_USER         SFTP username                                     [required]
  FTP_PASS         SFTP password                                     [required]
  FTP_PORT         SFTP port                                         [default 22]
  FTP_HOST_KEY     erwarteter SHA256-Fingerprint des Servers         [empfohlen]
                   (ohne -> es wird nur gewarnt und der Fingerprint ausgegeben)
  WEATHER_OUT_DIR  local dir with the *.json to upload               [default dist/weather]
  FTP_REMOTE_DIR   remote dir (relative to the SFTP home)            [default weather]

Note: on this Strato package the SFTP login already lands *inside* the
chiemsee-skipper web folder (feedback.php etc. sit right there), so the remote
dir is just "weather" -> served at huggie.de/chiemsee-skipper/weather/.

Exit codes: 0 ok, 1 config/no files, 2 authentication failed, 3 other SFTP error.
"""

from __future__ import annotations

import base64
import glob
import hashlib
import hmac
import os
import posixpath
import sys

import paramiko


def _clean(value: str | None) -> str:
    """Drop CR/LF anywhere and trim leading/trailing whitespace."""
    if not value:
        return ""
    return value.replace("\r", "").replace("\n", "").strip()


def main() -> int:
    host = _clean(os.environ.get("FTP_HOST"))
    user = _clean(os.environ.get("FTP_USER"))
    # Password: strip CR/LF and surrounding whitespace, but keep any inner spaces.
    raw_pass = os.environ.get("FTP_PASS") or ""
    password = raw_pass.replace("\r", "").replace("\n", "").strip()
    port = int(_clean(os.environ.get("FTP_PORT")) or "22")
    out_dir = os.environ.get("WEATHER_OUT_DIR") or "dist/weather"
    remote_dir = (_clean(os.environ.get("FTP_REMOTE_DIR")) or "weather").strip("/")

    if not host or not user or not password:
        print("::error::FTP_HOST / FTP_USER / FTP_PASS secret is missing.", file=sys.stderr)
        return 1

    files = sorted(glob.glob(os.path.join(out_dir, "*.json")))
    if not files:
        print(f"::error::no JSON files found in {out_dir}", file=sys.stderr)
        return 1

    print(f"user length={len(user)} pass length={len(password)}")
    print(f"Connecting to {host}:{port} as <user> -> uploading {len(files)} file(s) to {remote_dir}/")

    transport = paramiko.Transport((host, port))
    try:
        # SICHERHEIT: Erst die Identitaet des Servers pruefen, DANN das Passwort senden.
        # Ohne diese Pruefung koennte sich ein fremder Server dazwischenschalten
        # (Man-in-the-Middle) und das Webspace-Passwort im Klartext mitschneiden.
        transport.start_client(timeout=20)
        host_key = transport.get_remote_server_key()
        fingerprint = base64.b64encode(
            hashlib.sha256(host_key.asbytes()).digest()
        ).decode().rstrip("=")
        expected = _clean(os.environ.get("FTP_HOST_KEY"))
        if expected:
            if not hmac.compare_digest(expected, fingerprint):
                print(
                    "::error::SFTP host key mismatch! Erwartet SHA256:%s, Server meldet "
                    "SHA256:%s -- Upload abgebrochen (moeglicher Man-in-the-Middle)."
                    % (expected, fingerprint),
                    file=sys.stderr,
                )
                return 3
            print("Host key verified (SHA256:%s)." % fingerprint)
        else:
            print(
                "::warning::FTP_HOST_KEY ist nicht gesetzt - die Identitaet des Servers wird "
                "NICHT geprueft. Bitte den folgenden Fingerprint als GitHub-Secret "
                "FTP_HOST_KEY hinterlegen, dann wird ab dem naechsten Lauf geprueft."
            )
            print("::notice::FTP_HOST_KEY = %s" % fingerprint)
        try:
            transport.auth_password(username=user, password=password)
        except paramiko.AuthenticationException:
            print(
                "::error::SFTP authentication failed (server rejected user/password). "
                "Set FTP_USER / FTP_PASS to exactly the values that log in with WinSCP.",
                file=sys.stderr,
            )
            return 2

        sftp = paramiko.SFTPClient.from_transport(transport)
        assert sftp is not None

        # Create the remote directory chain (ignore components that already exist).
        cur = ""
        for part in remote_dir.split("/"):
            cur = part if not cur else posixpath.join(cur, part)
            try:
                sftp.mkdir(cur)
                print(f"  mkdir {cur}")
            except IOError:
                pass  # already exists

        for local in files:
            remote = posixpath.join(remote_dir, os.path.basename(local))
            sftp.put(local, remote)
            print(f"  put {os.path.basename(local)} -> {remote}")

        sftp.close()
        print("SFTP upload OK")
        return 0
    except Exception as exc:  # noqa: BLE001 - surface any SFTP/transport error clearly
        print(f"::error::SFTP upload failed: {exc}", file=sys.stderr)
        return 3
    finally:
        transport.close()


if __name__ == "__main__":
    raise SystemExit(main())
