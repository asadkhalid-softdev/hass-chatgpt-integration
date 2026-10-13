# Changelog

## 0.1.5

- Fix completed ChatGPT plan requests returning no answer: collect `response.output_item.done` events when the terminal `response.completed` event contains an empty output list.
- Keep collected output provisional until completion succeeds. Failed/incomplete/disconnected streams still cannot dispatch tools, and missing output indices are rejected.
- Report sanitized request and protocol errors in Assist instead of replacing every failure with one generic message.
- Verify live GPT-6.1 Sol text inference and a synthetic namespaced function-call round trip. Test both supported Core versions with 70 automated checks.

## 0.1.4

- Fix requests failing with `TypeError: Object of type _Unsupported is not JSON serializable` when Assist's probatio schemas were passed to the legacy voluptuous converter.
- Match Core's schema library for config forms and tool conversion, and use the current tool-result interface when available. Keep support for the older voluptuous-based Core API.
- Test the real Assist serializer, selectors and conversation tool-result handling against Core 2026.3.4 and 2026.10.1. CI checks both releases.

## 0.1.3

- Allow a fixed 30-second JWT clock-skew tolerance for minor differences in issuance, not-before and expiry timestamps. Signature, issuer, audience, required claims and nonce checks remain mandatory; tokens outside the timing tolerance are rejected.

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
