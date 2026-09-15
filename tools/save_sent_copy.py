#!/usr/bin/env python3
import imaplib
import os
import sys

host = os.getenv("BOSSMAIL_IMAP_HOST", "p212r.chinaemail.cn").strip()
port = int(os.getenv("BOSSMAIL_IMAP_PORT", "993"))
sender = os.getenv("BOSSMAIL_SMTP_USERNAME", "").strip()
password = os.getenv("BOSSMAIL_SMTP_PASSWORD", "").strip()
if not host or not sender or not password:
    raise RuntimeError("Bossmail IMAP is not configured")
message = sys.stdin.buffer.read()
if not message:
    raise RuntimeError("No message to save")
with imaplib.IMAP4_SSL(host, port, timeout=30) as client:
    client.login(sender, password)
    status, _ = client.append("INBOX.Sent", "\\Seen", None, message)
    if status != "OK":
        raise RuntimeError("Unable to append sent copy")
