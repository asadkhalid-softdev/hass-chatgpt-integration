# Changelog

## 0.8.1

- Make Alexa replies answer directly without follow-up questions, infer omitted periods from the current Home Assistant local clock, and preserve explicit historical dates.
- Bundle original transparent integration icons at standard and high-resolution Home Assistant brand sizes.

## 0.8.0

- Add a Reasoning effort selector to Configure with the documented Responses API effort values and a backward-compatible Model default option.
- Send the selected effort on every tool round for Assist, sidebar chat, and Alexa; report rejected reasoning settings without automatically retrying actions.

## 0.7.3

- Use an example Home Assistant domain in the Alexa setup guide and require each new installation to enter its own skill ID. Existing saved skill IDs and Echo pairings are preserved.

## 0.7.2

- Elicit the complete question after launch, help, fallback, or empty input, with short prompts and no required question prefix.
- Expand natural one-shot question patterns, including historical heater questions; update the bundled invocation to mister jarvis.
- Keep generation asynchronous, permissions unchanged, and replies scoped to the paired Echo.

## 0.7.1

- Unpaired Echos speak a stable six-digit code that matches the Home Assistant pairing selector.
- Show paired speaker names and list newly discovered speakers by last-heard time, without changing existing bindings or authorization.

## 0.7.0

- Add an opt-in signed Alexa endpoint with account/device pairing, independent background generation and targeted Alexa Media Player TTS.
- Use separate voice instructions and fresh context while saving Alexa turns to the existing sidebar transcript. Normal chat remains silent.
- Add voice length enforcement, replay protection, automatic sidebar refresh and setup instructions.

## 0.6.0

- Remove the global duplicate-ID editing blocker. Inspect duplicate definitions with entry indexes and edit one entry in place; preserve siblings and block stale indexed snapshots. Support unused ID repairs and valid blueprint-input updates.
- Enable direct automation apply/restore from chat for authenticated administrators within existing selected grants, with validation, sealed proposals, backups and conflict checks. Dashboard changes retain mandatory review; direct automation mode can be disabled.
- Add native administrator log discovery/read tools enabled by default: Core condensed/live/file logs, activity, traces, Supervisor, discovered apps, plugins and host journals/boot offsets where supported.
- Add bounded paging/search, native read-only adapters, best-effort credential redaction and old-context/demotion checks. Show direct-update/log capability indicators and document the changed defaults and installation-specific limits.

## 0.5.2

- Render GitHub Flavored Markdown in sidebar replies: proper tables with aligned headers/cells, headings, nested lists, read-only tasks, quotes, emphasis/strikethrough, rules and labeled code blocks.
- Keep tables horizontally scrollable inside mobile messages and support keyboard focus. Render HTML/images as inert text and allow only credential-free HTTP(S) links.
- Bundle a pinned, MIT-licensed Marked lexer locally, render its tokens through a DOM allowlist, and update the frontend cache version. Add parser reproduction and browser formatting/security/layout checks.

## 0.5.1

- Group automation, dashboard and sensor-history checklists into native collapsible permission sections, closed initially. Keep general capability switches visible and open affected sections after bulk actions or validation errors.
- Preserve existing flat stored grants while processing nested Home Assistant form submissions; keep Select all/none and draft review behavior unchanged.
- Update the README with HACS installation, all current capabilities and the independent history permission/privacy boundary.

## 0.5.0

- Add separately permissioned, read-only sensor history with a named sensor checklist and Select all / Select none controls. History can be enabled without device control or configuration drafting.
- Add scoped history discovery and Recorder reads for recent raw readings and longer hourly/daily statistics, with explicit timezone-aware intervals, bounded results and missing/truncated data markers.
- Check the authenticated user's entity permissions before querying and after database reads; prevent forwarding old history tool results after grants are revoked.
- Add history setup and privacy documentation plus Core conversation, permission and SQLite Recorder tests.

## 0.4.1

- Add Select all / Select none checkboxes for automation and dashboard permissions. Submit refreshes the selections for review; a second submission saves explicit grants. Bulk controls never grant future discoveries.
- Clear new automation ID reservations when selecting no automations, and reject conflicting bulk controls.

## 0.4.0

- Add a locally served ChatGPT Assist sidebar panel with themed desktop/mobile chat, message history, reply indicator, citations, code blocks, copying and account selection. Enter sends; Shift+Enter inserts a newline and IME composition does not submit.
- Add an authenticated, per-user/per-account history backend with bounded private storage and restoration of native conversation context after reload/expiry. No OAuth credentials are sent to the browser.
- Add Clear message history in the chat menu with confirmation. Clear removes the selected user’s persisted messages and active Core conversation context; no New conversation button is shown.
- Prevent duplicate delivery, concurrent turns/clear and cross-user or unauthorized administrator-history access. Register one sidebar panel and remove it when the last account unloads.
- Add real Core backend tests and Chromium interaction/security/layout tests, plus browser checks in CI.

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
