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

Disabled by default, with separate exact-target allowlists for automation IDs and storage dashboard paths. With administration enabled, the conversation agent also checks administrator identity before sending any conversation history to the model. After disabling administration, conversations containing configuration tool results must be replaced with a new conversation. Every model configuration tool checks the original requesting HA user's active administrator status; missing and system-generated identities are denied. Tools are scoped to this account's conversation agent and are not globally registered with Assist or MCP. The only model write tool persists a draft; no model tool, service or chat confirmation can apply or approve it.

Approval/restoration happens through HA's options-flow endpoints, which require an authenticated administrator on both flow creation and submission. The server applies its saved proposal after checking author permissions, current allowlists, expiry, content hashes, current target configuration and validation. A different administrator may review a draft, but the original author must still have active administrator access. Proposals cannot alter their automation ID. Package/custom-include automations and automations without IDs are read-only. Source inspection uses only Core’s recorded source path inside the config directory, checks the loaded identity and returns YAML tag references without resolving them. Runtime configurations containing resolved secrets are never returned as the inspection fallback. Blueprints, YAML dashboards, secret/include resolution, dashboard resource installation and arbitrary file paths are excluded.

Backups are persisted before live writes. Interrupted/failed writes are not automatically retried. Restoration requires review and an unchanged applied target; later edits block it. The bounded private HA storage record contains configuration and author IDs, not credentials. Private storage is not encryption. Native/external editors do not share this integration's lock, so avoid concurrent editing during application. Structural dashboard validation cannot certify arbitrary custom cards. Automation actions may invoke powerful existing services/scripts: approval grants those effects, so review every action.

Selected configurations, drafts and tool arguments may be sent to OpenAI and recorded by HA traces. Protect backups and avoid literal credentials in allowed configuration. See [administration guide](docs/ADMINISTRATION.md) for supported scope and recovery.

## Hosted internet search

Internet search is disabled by default and separate from device and administration permissions. When enabled, the request includes OpenAI’s hosted `web_search` tool; HA does not execute a browser, scrape pages or fetch citation URLs. Search queries leave HA. They may be based on conversation/home context already sent to OpenAI. Prompt guidance asks for generic public queries and treats webpages as untrusted data, but cannot enforce query privacy or intercept hosted searches before execution. Avoid sharing sensitive configuration in search-enabled conversations.

Completed search items are retained unchanged in native conversation history. Only completed, recognized search items are accepted when search is enabled. Duplicate IDs, unknown tool kinds, malformed citations and excessive completed tool counts reject the entire output before HA dispatch. Transport failures never return provisional actions. The eight-call limit is a client-side validation limit; it cannot prevent OpenAI from running additional hosted searches before returning output. There is no automatic search retry, silent downgrade or OAuth retry on policy failures.

Generated citation links accept HTTP(S), reject credentials and known local/private literal addresses, validate hostname/port syntax and escape Markdown/HTML URL delimiters. Citation titles are not interpolated into markup. Links do not guarantee a trustworthy website and are opened only by the user’s client. Provider citation indices are applied to display text; raw output remains untouched for subsequent requests. Existing exposure, authenticated administrator and separate configuration approval boundaries still apply.

## Sidebar chat

The sidebar serves only local static JavaScript. Its API runs through Home Assistant’s authenticated WebSocket connection. User identity and action Context come from that connection; clients cannot submit an owner, agent ID, conversation ID, archived context or approval. Registered ChatGPT Assist entries are resolved to their actual conversation entity. Existing exposed-entity permissions and administrator configuration approval remain in effect.

Messages and native model/tool context are kept separately for each HA user/account in the private `.storage/chatgpt_assist.sidebar_history` record. This is not an encrypted vault. History containing administrator context stays inaccessible after that user loses administrator privileges, even when administration is later disabled. Hosts/backups and HA administrators remain trusted. The browser uses no local/session storage for transcripts or OAuth tokens. User switches clear visible messages and drafts immediately.

Request IDs prevent repeated delivery while a message remains retained. The user message and pending reply are persisted before inference, and concurrent send/clear operations are blocked per chat. Interrupted or failed requests are never automatically replayed. Native context is restored as data without reconstructing executable ToolInput objects; only fresh provider output can dispatch actions. Context is trimmed at whole-turn boundaries and stored as plain JSON data, excluding arbitrary dict-subclass attributes.

The Clear history action removes the selected user/account’s saved messages/context and its active Core chat session. It does not delete independent HA traces, backups, configuration proposals or provider-retained data. Removing an integration entry removes its sidebar histories. Displayed history is bounded to 60 messages/128 KB; native context to 160 KB; at most 100 user/account histories are retained. Message input is bounded to 4,000 characters and displayed replies to 16,000 characters.

A pinned, locally bundled Marked lexer parses Markdown into tokens. An allowlisted DOM renderer formats tables, lists, headings and text without interpreting model output as HTML. Entity references alone are decoded, then inserted as text nodes. Renderer nesting/token limits and a plain-text fallback protect malformed responses; no message HTML, scripts or image embeds are executed. Code blocks are text. Clickable links allow only credential-free HTTP(S), open with `noopener noreferrer`, and never fetch remotely inside HA. Python permission tests and browser tests cover ownership, context reset, injection, key handling, request deduplication, identity changes and mobile layout.

## Sensor history

History access defaults off and uses explicit sensor/binary-sensor grants. Queries require an active authenticated user with entity read permission, use read-only Core Recorder APIs and return state/timestamp or numeric statistic fields without arbitrary attributes. Actor and grant permissions are checked again after reads and before forwarding old tool results. Historical data is sent to the selected ChatGPT account and can remain in private sidebar history or HA traces; revoking access does not erase existing records. Time windows and output are bounded; the underlying Recorder API may still materialize many readings per hourly raw chunk. See [history limits](docs/HISTORY.md).
