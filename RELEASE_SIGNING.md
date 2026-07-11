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

## Rotate to the verified certificate

Before replacing the PFX secret, publish one transition release signed by the current certificate and set:

- `WINDOWS_NEXT_SIGNING_CERTIFICATE_SHA256`

The value must be the 64-character SHA-256 fingerprint of the future certificate. The transition release embeds both certificate pins. After users install that build, replace the PFX/password secrets and publish with the verified certificate.

## Limitation

The release is technically signed and accepted by FreeCleaner's pinned updater, but Windows SmartScreen may still warn until the certificate is publicly trusted and has sufficient reputation.
