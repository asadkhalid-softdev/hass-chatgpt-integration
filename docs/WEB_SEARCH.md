# Internet search

Version 0.3.0 can use OpenAI’s hosted web-search tool with your existing ChatGPT account connection. It is optional and starts disabled. OpenAI documents this capability on the ChatGPT plan route, subject to the selected model and account/workspace policy. It does not promise availability for every account. [Official preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)

## Enable and verify

1. Push the update, update/redownload **ChatGPT Assist** in HACS, and restart Home Assistant.
2. Open **Settings → Devices & services → ChatGPT Assist → Configure → Model and permissions**.
3. Enable **Allow internet search** and save. You can leave device control and configuration administration off for a search-only assistant.
4. Start a new conversation and ask: “Search the internet for the latest Home Assistant release notes and cite the official source.”
5. Check the clickable source links in the text response. Follow the link to confirm the result matches the current page.

Your existing OAuth grant is used. There is no separate search-provider key or new sign-in step for this feature. The model decides when to search; enabling it makes search available rather than forcing a lookup for every message. Explicitly ask for an internet search when you want a live lookup.

Citations are generated from OpenAI’s URL annotations and shown as numbered inline Markdown links. Duplicate links at the same position are combined. Opaque provider citation markers are replaced for display; original output is preserved for the next turn. Unsafe citation URLs are omitted. Native Assist clients determine link rendering; voice-only clients may read source links aloud or have no display for them. [OpenAI web-search and citation format](https://developers.openai.com/api/docs/guides/tools-web-search)

## Access errors

If OpenAI rejects search for your model, account or workspace, Assist displays the sanitized provider error and suggests disabling **Allow internet search** or choosing another available model. Do that manually and start a new conversation. The integration does not silently switch providers, retry inference or force account reauthentication for a policy rejection.

An error after an earlier device action does not undo that action. Check device state before repeating an instruction. Completed search items and earlier text remain in the conversation log. Turning search off prevents new search tools from being offered; it does not erase previously retrieved information.

## Privacy and permissions

Queries are executed by OpenAI’s hosted tool, outside HA. Your conversation and any enabled home context are already sent to OpenAI for inference, and the model may use that context to formulate search queries. Guidance asks for generic public terms and excludes private device/configuration details, but this is prompt guidance rather than an enforceable privacy filter. Avoid sensitive context in search-enabled conversations.

Search results do not authorize HA actions. Exposed-device rules still apply; configuration administration still requires an authenticated administrator and separate human review. Searches do not grant access to additional entities, files or settings.

Each turn has a 180-second timeout and an eight-call completed-output validation budget shared by hosted searches and HA tools. Hosted searches occur on OpenAI’s side before the integration receives the completed output, so this budget cannot prevent additional provider-side searches or their usage. No unsupported `max_tool_calls` parameter is sent on the ChatGPT plan route.

## Verification status

Automated tests cover the real HA conversation log, settings form, search-only responses, search/HA-tool combinations, draft permissions, SSE reconstruction, failed search streams, citation rendering and unsafe URLs against Core 2026.3.4 and 2026.10.1. Network responses in these tests are local or mocked. Live hosted search with your current account still needs the first verification request above; successful text inference alone does not establish search eligibility.
