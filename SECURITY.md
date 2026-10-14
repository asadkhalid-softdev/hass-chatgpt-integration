# Security model

## Trust boundaries

The local helper obtains a public-client OAuth grant using random state, OIDC nonce and S256 PKCE. Its HTTP callback binds only to 127.0.0.1, checks Host and state, rejects duplicate query fields and consumes the callback once. Access logs are disabled. ID tokens are verified using OpenAI's fixed HTTPS JWKS endpoint, with RS256, issuer, audience, expiry, required claims and nonce checks. JWT time checks allow a fixed 30-second clock-skew tolerance; larger differences remain errors. Returning sign-in must retain client ID and signed subject. No OAuth client secret or ChatGPT password is collected.

The HA admin config flow imports credentials and checks the access token's signature, resource audience, issuer, expiry, client registration, subject and scopes. Token/JWKS/API endpoints are fixed; HTTP redirects are disabled. The browser helper and HA exchange no unauthenticated network messages. Transfer must use a secure HA UI connection; the integration cannot enforce your reverse proxy's TLS configuration.

Only Home Assistant's built-in Assist API is offered to the model. Available names and schemas are checked before dispatch. HA carries the original user's Context and controls entity exposure and supported intents. This integration provides no arbitrary service, filesystem, configuration or code execution tools. It does not add a separate per-user entity authorization layer; use HA's Assist exposure controls and treat selecting this conversation agent as granting access to the exposed home.

## Credential lifecycle

On Unix, helper files are atomically written with mode 0600; new directories use 0700. On Windows, the helper applies a protected DACL containing only the current account before writing any credential content, checks the resulting ACL, then atomically replaces the destination file. Failure to set or verify the ACL stops the write. This requires NTFS and the helper-only pywin32 dependency. An existing parent directory's permissions are the user's responsibility. Retained credentials allow later authorization of the same registration; the helper never refreshes the HA session.

HA config-entry storage holds the imported grant. A dedicated HA Store holds the latest rotated grant with immediate atomic writes. Runtime loads the newest matching registration at startup. One lock serializes refreshes per entry. The new rotating grant is saved before use; duplicate registrations are rejected through unique IDs. Reauthentication preserves HA's opaque host ID. Removal revokes the current refresh token if possible, deletes the rotated store and warns through a persistent notification if remote revocation was not confirmed.

HA storage and backups are not an encrypted secret vault. Restrict host access, encrypt off-host backups and protect your HA administrator account. A process crash between provider rotation and local persistence can still lose a refresh token; reauthorize if that happens. Do not run multiple HA instances from the same credentials or let another client refresh the copied session.

## Model execution

Device access defaults off. With it enabled, an LLM may trigger any supported intent for exposed entities, including exposed scripts. Exposure limits targets; it does not guarantee the model correctly understands the user's intent. Prompt instructions are secondary guidance, not a security boundary. There is no interactive approval step for each write and no mode that exposes only read tools.

Responses must finish successfully before their tool calls execute. The entire batch must have recognized names/namespaces, object arguments, valid parameter schemas and fresh call IDs. Unknown tool types, duplicate calls and more than eight calls fail closed. Each turn has a time limit and transport/input size limits. There are no automatic inference retries. A later failure can occur after earlier actions succeeded; these actions cannot be rolled back automatically.

The provider still sees request data despite `store=false`. Your HA logging/tracing settings may record conversation and tool data. Avoid broad debug/HTTP logging and never upload `.storage` or helper account files for support. Diagnostics use an explicit safe field allowlist.

## Reporting

Report security problems privately to the repository maintainer once this project has a published repository and contact channel. No reporting address is configured in this local initial release. Never include live tokens, full credentials or private home data. If credentials are exposed, disconnect the app in ChatGPT Settings and replace the local session.

## Configuration administration

Configuration access requires an active authenticated administrator and explicit automation/dashboard grants. Version 0.6.0 enables direct automation apply/restore tools by default within that authority; disable `automation_apply` to retain manual review. Direct tools accept only a sealed, validated automation proposal belonging to that administrator. They cannot apply dashboards, arbitrary replacement text or someone else's proposal. Dashboard mutations always require HA's administrator-protected review flow.

Backups and intent are persisted before live writes. Duplicates are inspectable and selected with an explicit entry index; only the selected entry is replaced. Indexed writes check the whole editor snapshot because reordering can change an index's identity. Normal unique-target writes check the target and preserve other entries. Valid ID repairs are supported, and successful renames retain the original grant and add the new ID. Restoration verifies the applied target, saved seals, grants and current administrator role. Failed/interrupted operations are not automatically replayed.

Package/custom-include sources remain read-only. Secret/include tag resolution, arbitrary file edits, unsupported editor-file structures, YAML dashboards and dashboard resource installation remain outside mutation scope. Valid blueprint inputs can be edited, but not blueprint source files. Native/external editors do not share the mutation lock; avoid concurrent writes. Automated validation cannot guarantee the intended physical effects. Automation actions can invoke powerful HA services/scripts; direct mode trusts the administrator's delegated instructions and the model's decisions within its grants. Prompt guidance is not an independent approval boundary.

Selected configurations, proposals and tool arguments can be sent to OpenAI and recorded in HA traces. Protect the bounded private proposal store and backups; private storage is not encryption. See the [administration guide](docs/ADMINISTRATION.md).

## Hosted internet search

Internet search is disabled by default and separate from device and administration permissions. When enabled, the request includes OpenAI’s hosted `web_search` tool; HA does not execute a browser, scrape pages or fetch citation URLs. Search queries leave HA. They may be based on conversation/home context already sent to OpenAI. Prompt guidance asks for generic public queries and treats webpages as untrusted data, but cannot enforce query privacy or intercept hosted searches before execution. Avoid sharing sensitive configuration in search-enabled conversations.

Completed search items are retained unchanged in native conversation history. Only completed, recognized search items are accepted when search is enabled. Duplicate IDs, unknown tool kinds, malformed citations and excessive completed tool counts reject the entire output before HA dispatch. Transport failures never return provisional actions. The eight-call limit is a client-side validation limit; it cannot prevent OpenAI from running additional hosted searches before returning output. There is no automatic search retry, silent downgrade or OAuth retry on policy failures.

Generated citation links accept HTTP(S), reject credentials and known local/private literal addresses, validate hostname/port syntax and escape Markdown/HTML URL delimiters. Citation titles are not interpolated into markup. Links do not guarantee a trustworthy website and are opened only by the user’s client. Provider citation indices are applied to display text; raw output remains untouched for subsequent requests. Existing exposure, administrator identity, target grants and the selected direct/manual mutation mode still apply.

## Sidebar chat

The sidebar serves only local static JavaScript. Its API runs through Home Assistant’s authenticated WebSocket connection. User identity and action Context come from that connection; clients cannot submit an owner, agent ID, conversation ID, archived context or approval. Registered ChatGPT Assist entries are resolved to their actual conversation entity. Existing exposed-entity permissions, administrator grants and direct/manual mutation controls remain in effect.

Messages and native model/tool context are kept separately for each HA user/account in the private `.storage/chatgpt_assist.sidebar_history` record. This is not an encrypted vault. History containing administrator context stays inaccessible after that user loses administrator privileges, even when administration is later disabled. Hosts/backups and HA administrators remain trusted. The browser uses no local/session storage for transcripts or OAuth tokens. User switches clear visible messages and drafts immediately.

Request IDs prevent repeated delivery while a message remains retained. The user message and pending reply are persisted before inference, and concurrent send/clear operations are blocked per chat. Interrupted or failed requests are never automatically replayed. Native context is restored as data without reconstructing executable ToolInput objects; only fresh provider output can dispatch actions. Context is trimmed at whole-turn boundaries and stored as plain JSON data, excluding arbitrary dict-subclass attributes.

The Clear history action removes the selected user/account’s saved messages/context and its active Core chat session. It does not delete independent HA traces, backups, configuration proposals or provider-retained data. Removing an integration entry removes its sidebar histories. Displayed history is bounded to 60 messages/128 KB; native context to 160 KB; at most 100 user/account histories are retained. Message input is bounded to 4,000 characters and displayed replies to 16,000 characters.

A pinned, locally bundled Marked lexer parses Markdown into tokens. An allowlisted DOM renderer formats tables, lists, headings and text without interpreting model output as HTML. Entity references alone are decoded, then inserted as text nodes. Renderer nesting/token limits and a plain-text fallback protect malformed responses; no message HTML, scripts or image embeds are executed. Code blocks are text. Clickable links allow only credential-free HTTP(S), open with `noopener noreferrer`, and never fetch remotely inside HA. Python permission tests and browser tests cover ownership, context reset, injection, key handling, request deduplication, identity changes and mobile layout.

## Sensor history

History access defaults off and uses explicit sensor/binary-sensor grants. Queries require an active authenticated user with entity read permission, use read-only Core Recorder APIs and return state/timestamp or numeric statistic fields without arbitrary attributes. Actor and grant permissions are checked again after reads and before forwarding old tool results. Historical data is sent to the selected ChatGPT account and can remain in private sidebar history or HA traces; revoking access does not erase existing records. Time windows and output are bounded; the underlying Recorder API may still materialize many readings per hourly raw chunk. See [history limits](docs/HISTORY.md).

## Native administrator logs

Native log access defaults enabled for authenticated administrators. Non-administrators receive no log tools; ordinary household chat remains available when configuration administration is off. Sources are discovered from native APIs, registered logger files and log-shaped files directly in the config directory. No model-supplied URL, arbitrary path, shell command or log mutation is accepted. Supervisor calls use fixed GET endpoints and HA's existing internal credentials, without redirects. Data is bounded and credentials are redacted best-effort before provider output. Third-party log text can still contain unrecognized secrets/private data.

The live Core handler respects existing logger levels and retains at most 5,000 records/512 KB. It is detached when the last enabled account unloads. File/API output windows are bounded; native activity/trace/condensed operations may materialize more data before output trimming. Actor access is rechecked after reads and on later turns with old log context. Sidebar administrator histories remain protected after demotion. Logs can remain in private archives/HA traces after access is disabled. See [log privacy and limits](docs/LOGS.md).
