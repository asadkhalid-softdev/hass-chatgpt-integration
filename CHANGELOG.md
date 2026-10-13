# Changelog

## 0.3.0

- Add opt-in hosted internet search using the existing ChatGPT account grant, independent of device/configuration access.
- Preserve completed web-search output in conversation history and render safe, clickable inline source citations without changing native provider items.
- Reject disabled, failed, duplicated or excessive search output before HA tool dispatch; retain sanitized provider errors with actionable search-access guidance and no automatic retry.
- Document setup, account/model limitations, hosted-query privacy and client-side limits. Test search-only chats, HA tool combinations, configuration drafts, citation safety and streamed search failures on both supported Core versions.

## 0.2.2

- Populate automation permissions from Core’s loaded automation entities when editor-file discovery fails. Include package/custom-include automations and entries without IDs as read-only selections.
- Inspect original YAML using Core source locations without returning resolved runtime secrets. Preserve secret/include tags as reference metadata; reject outside-directory sources, stale identities, YAML merge aliases and recursive structures.
- Show specific, sanitized editor-access diagnostics and recognize equivalent standard include paths. Keep edits restricted to supported editor-file entries.

## 0.2.1

- Replace manual permission IDs with native HA checklists displaying automation names and storage dashboard titles. Preserve legacy grants, including reserved/missing targets, and select no additional resources automatically.
- Keep new automation reservations as a separate optional field, validate IDs, and explain unavailable discovery in the permissions form.
- Include names of allowed targets in the assistant configuration-list tool so users can refer to their selections by name.

## 0.2.0

- Add opt-in administrator configuration tools for exact allowed automation IDs and storage dashboard paths. Read full saved definitions, validate replacement drafts, and report proposal status.
- Add native Configure review/approval and restoration forms. Chat tools cannot approve or apply changes. Proposals expire in 30 minutes, enforce active administrator permissions and conflict checks, and save bounded private backups before writing.
- Support creating UI-managed automations under preauthorized IDs, atomic automation saves/reloads, and existing dashboard view/card updates through HA storage. Document unsupported blueprint/YAML/dashboard-registration operations and concurrency limits.
- Add real HA configuration validation, storage, review-flow, permission, failure and restoration tests for both supported Core versions.

## 0.1.6

- Surface sanitized provider failure codes and request-parameter roots for failed/incomplete streams and bounded HTTP error responses. Distinguish app/plan limits, eligibility, unsupported capabilities, model availability and temporary service failures.
- Keep provider message/detail fields and dynamic parameter names out of Assist and logs. Add safe failure messages to the integration log.
- Preserve credentials for HTTP 403 policy/eligibility restrictions rather than starting an OAuth retry loop.

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
