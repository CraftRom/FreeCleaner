# FreeCleaner release signing

The release workflow requires these GitHub Actions secrets:

- `WINDOWS_SIGNING_CERTIFICATE_BASE64`
- `WINDOWS_SIGNING_CERTIFICATE_PASSWORD`

A self-signed code-signing certificate is published through the normal release path. The Windows runner temporarily imports that certificate into the current user's `Root` and `TrustedPublisher` stores so both the packaged EXE and Inno Setup installer can be validated during CI.

Before PyInstaller runs, the workflow embeds the exact SHA-256 certificate fingerprint into `freecleaner/build_trust.py`. On user machines, FreeCleaner accepts an untrusted self-signed chain only when all of the following match:

1. Authenticode signer certificate is present;
2. certificate subject matches the expected publisher;
3. certificate is self-signed (`Subject == Issuer`);
4. certificate SHA-256 matches an embedded release pin;
5. the WinVerifyTrust failure is specifically `CERT_E_UNTRUSTEDROOT`.

A different certificate using the same `CN=FreeCleaner` is rejected.

## Create the current certificate

Run on Windows:

```bat
scripts\create_self_signed_release_certificate.bat
```

Copy the generated values to repository Actions secrets, then delete the local `signing-secrets` directory.


## Fixing an invalid existing PFX

The two GitHub secrets must come from the same generated PFX and password. A normal TLS certificate or a generic OpenSSL self-signed certificate is not sufficient: the certificate must contain the private key and the Code Signing extended key usage `1.3.6.1.5.5.7.3.3`.

The current generator re-imports the exported PFX and verifies both requirements before writing the secret files. Run it again and replace **both** repository secrets when CI reports either a missing private key or a missing Code Signing EKU:

```bat
scripts\create_self_signed_release_certificate.bat
```

Copy the complete contents of these files, not their paths or filenames:

- `signing-secrets\WINDOWS_SIGNING_CERTIFICATE_BASE64.txt` → `WINDOWS_SIGNING_CERTIFICATE_BASE64`
- `signing-secrets\WINDOWS_SIGNING_CERTIFICATE_PASSWORD.txt` → `WINDOWS_SIGNING_CERTIFICATE_PASSWORD`

Replacing only one secret creates a password/PFX mismatch.

## Rotate to the verified certificate

Before replacing the PFX secret, publish one transition release signed by the current certificate and set:

- `WINDOWS_NEXT_SIGNING_CERTIFICATE_SHA256`

The value must be the 64-character SHA-256 fingerprint of the future certificate. The transition release embeds both certificate pins. After users install that build, replace the PFX/password secrets and publish with the verified certificate.

## Limitation

The release is technically signed and accepted by FreeCleaner's pinned updater, but Windows SmartScreen may still warn until the certificate is publicly trusted and has sufficient reputation.
