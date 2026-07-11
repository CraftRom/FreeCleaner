"""Build-time update trust anchors.

The release workflow overwrites these values before PyInstaller packaging.
Source checkouts intentionally keep them empty.
"""

UPDATE_SIGNING_CERT_SHA256 = ""
UPDATE_SIGNING_CERT_SHA256_PINS: tuple[str, ...] = ()
UPDATE_SIGNING_CERT_SUBJECT = ""
