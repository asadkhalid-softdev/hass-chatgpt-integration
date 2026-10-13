# Changelog

## 0.1.2

- Consume complete OAuth, JWKS and model-list HTTP bodies before parsing JSON, keeping a strict response-size limit. Add real split-response transport tests and safe network/parse error codes.

- Report safe JWT verification failure codes without exposing tokens or account claims, so live sign-in failures can be diagnosed without weakening verification.

- Support native PowerShell/Windows sign-in with protected NTFS credential-file ACLs; test successful writes and fail-closed permission errors on native Windows.
- Declare helper dependencies using inline script metadata and document one-line `uv run --script` commands, avoiding project discovery and Bash line-continuation errors in PowerShell.

## 0.1.1

- Remove integration dependency pins for libraries already supplied by Home Assistant. The `PyJWT[crypto]==2.10.1` requirement could fail installation and prevent the config flow from loading.
- Restore parenthesized exception tuples so modules parse on Python 3.12 and 3.13 as well as 3.14.
- Set the formatter's Python target to 3.12 and add syntax regression checks for every integration module and the sign-in helper. This does not extend the tested Home Assistant API baseline beyond 2026.3.4.

## 0.1.0

- Initial ChatGPT account-backed Assist integration and local OAuth sign-in helper.
