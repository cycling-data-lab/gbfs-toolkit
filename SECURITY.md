# Security policy

## Supported versions

Security fixes are applied to the latest released minor version on PyPI. Please upgrade to the
current release before reporting.

## Reporting a vulnerability

`gbfs-toolkit` performs network requests in its optional `[fetch]` layer (feed discovery and
polling). If you find a security issue, for example a way to make the fetcher exfiltrate data,
follow a malicious redirect, or exhaust resources, please report it privately rather than opening a
public issue.

- Email **rfosse@cesi.fr** with a description and a minimal reproducer.
- Alternatively, use GitHub's private vulnerability reporting
  ("Report a vulnerability" under the repository's Security tab).

We aim to acknowledge within a few working days and to coordinate a fix and disclosure timeline with
you. The core analysis layer makes no network calls by design, so most of the attack surface is in
`[fetch]`.
