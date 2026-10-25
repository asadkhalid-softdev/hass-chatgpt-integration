# ChatGPT Assist for Home Assistant

A custom conversation integration that signs in with your **ChatGPT account** and uses eligible account models in Home Assistant Assist. Device access is opt-in and uses Home Assistant's built-in Assist API.

**Status:** version **0.8.1**, tested against Home Assistant Core **2026.3.4** and **2026.10.1**, Python **3.14**. OAuth and inference follow the documented OpenAI OSS preview. Live GPT-6.1 Sol text inference and a synthetic function-call round trip have been verified. Your account eligibility and a real home installation still require your verification. Other Home Assistant versions have not been verified. This is an independent project, not an official OpenAI or Home Assistant integration.

## What it does

- Optional signed Alexa HTTPS endpoint with explicitly paired Echo delivery, fresh voice context, and transcript-only sidebar history. See the [Alexa guide](docs/ALEXA.md).

- Query past temperature, humidity and other selected sensors through read-only Recorder history and hourly/daily statistics. History has its own opt-in permission and works with device control disabled. See the [sensor history guide](docs/HISTORY.md).
- Manage automation, dashboard and history-sensor grants in separate **collapsible sections**, closed initially, with named checklists and Select all/none controls. Bulk selection refreshes the checklist for review before saving; future discoveries are never automatically granted.
- Inspect and directly update selected automations from chat when configuration access is enabled, including individual duplicate-ID entries and valid blueprint inputs. Save backups and restore them on request. Direct automation updates start enabled; turn them off to require Configure review. Dashboard changes always require review.
- Read all available native log sources as an authenticated administrator: Core errors/live/file logs, activity, automation/script traces, Supervisor/apps/plugins and host journals where available. Log access starts enabled for administrators and can be disabled. Credentials are redacted best-effort. See the [log guide](docs/LOGS.md).
- Optionally search the internet through OpenAI’s hosted web-search tool and show clickable source citations in Assist. Search starts disabled and depends on model/account eligibility. See the [internet search guide](docs/WEB_SEARCH.md).
- Open **ChatGPT Assist** from the sidebar for a dedicated chat with private per-user history, Enter to send, Shift+Enter for new lines, a **Clear message history** menu option, and formatted Markdown tables, headings, lists, quotes and code. See the [sidebar chat guide](docs/SIDEBAR_CHAT.md).
- Discover models available to the authorized ChatGPT account.
- Choose **Reasoning effort** in Configure: Model default, None, Minimal, Low, Medium, High, Extra high, or Maximum. Applies to sidebar chat and Alexa; support depends on the model/account. Existing installations keep the model default until changed. See [reasoning settings](docs/REASONING.md).
- Answer questions in Assist and retain conversation context through Home Assistant's chat log.
- Read live home information and control exposed entities when you enable device access: for example lights, supported thermostat settings, and exposed scenes/scripts.
- Validate OAuth state, PKCE, ID-token signatures, issuer, audience, expiry and nonce. Verify signed access-token identity again on import.
- Renew tokens with serialized, atomic storage of rotating refresh tokens; provide reauthentication when a session is revoked.
- Bound each turn to 8 accepted tool calls and 180 seconds. HA actions run sequentially; hosted searches execute on OpenAI’s side before their completed output is validated. Validate tool names, namespaces, argument schemas and duplicate call IDs before executing a response.

Optional [configuration administration](docs/ADMINISTRATION.md) can inspect and draft changes to explicitly allowed UI-managed automations and existing storage dashboards. Direct automation changes use validation, conflict checks and saved backups. Dashboard changes, and automations when direct mode is disabled, require administrator review in Configure. This includes creating automations under IDs you explicitly allow. Package/YAML dashboard editing, integration installation, arbitrary services and shell access are unsupported.

## Why sign-in uses a helper

OpenAI documents dynamic OAuth registration for open-source, locally hosted clients, including eligible ChatGPT plan inference. It requires a `127.0.0.1` browser callback. That callback reaches your browser's computer, whereas Home Assistant commonly runs elsewhere. The included helper completes OAuth locally and produces a private credential file, following OpenAI's documented self-hosted transfer procedure. You import that file into HA over a secure connection; HA then owns refreshes.

There is no client secret to obtain, no borrowed Codex client ID, no ChatGPT browser-cookie extraction and no private `backend-api` endpoint. The general commercial partner sign-in program has separate availability requirements. The OSS flow is a preview: account/workspace policy, plan permissions and usage limits determine availability. If OpenAI does not enable it for your account, this integration cannot bypass that restriction. Use HA's official **OpenAI Conversation** integration with an API key if you need that alternative; its billing is separate from ChatGPT plan use.

## Install

Full instructions: [Installation guide](docs/INSTALLATION.md).

1. In **HACS → Custom repositories**, add `https://github.com/asadkhalid-softdev/hass-chatgpt-integration` with category **Integration**. Find **ChatGPT Assist**, download it, and restart HA. For updates, use HACS **Update** or **Redownload** from the default branch, then restart HA.
2. On your browser's computer, run this single line in PowerShell or Bash with `uv` installed. The helper manages its own dependencies:

   ```text
   uv run --python 3.12 --script scripts/chatgpt_login.py
   ```

3. Open HA over HTTPS → **Settings → Devices & services → Add integration → ChatGPT Assist**. Paste the protected JSON credential file, then choose a model.
4. Open **ChatGPT Assist → Configure → Model and permissions**. Enable only the capabilities you want. Device control uses entities exposed under **Settings → Voice assistants → Expose**. Expand **Automations**, **Dashboards** and **Sensor history** to select grants for those separate capabilities; each section starts collapsed. Select all/none requires submitting once to refresh the checklist and again to save.
5. Edit or add an assistant under **Settings → Voice assistants** and select the new **ChatGPT Assist** conversation agent. Speech recognition and text-to-speech are configured separately.

For manual installation, copy `custom_components/chatgpt_assist` into your HA configuration's `custom_components/` directory and restart HA. To run the login helper, clone or download this repository onto the computer running your browser; HACS installs only the integration on the HA host.

You can add multiple account/workspace registrations by using separate helper output files and adding separate integration entries. The integration title uses an issued client-ID suffix to distinguish registrations. Removing an entry attempts remote session revocation and removes its local rotated-token store.

## Security and privacy

See [Security model](SECURITY.md). Your questions, conversation context and Assist's exposed home context are sent to OpenAI. `store=false` avoids Responses application storage; it does not promise zero provider retention. This flow grants no access to your ChatGPT chat history. Home Assistant owns its chat logs and storage policies.

Tokens are sensitive secrets. The helper writes owner-only files on Unix and protected files accessible to the current account on Windows NTFS. HA stores initial credentials in its normal config-entry storage and renewed credentials in a dedicated atomic `.storage` record, **not an encrypted vault**. Secure your HA host and backups, access the UI over HTTPS, and revoke the app in ChatGPT Settings if credentials leak. Do not turn on broad HTTP/debug logging or include credential files in bug reports.

A model can misunderstand requests or follow malicious device text. Device exposure controls Assist device access; explicit checklists independently control sensor history and configuration access. Avoid exposing door locks, alarms and powerful scripts until you have assessed the consequences. Assist device actions have no per-action confirmation UI or separate read-only mode. Direct automation mode permits writes from chat instructions without a separate confirmation. Dashboard edits always require review; automation review is available by disabling direct mode. History queries are read-only and return only selected sensors the requesting HA user may read. Native log tools remain available to administrators unless separately disabled. With device control, configuration access, sensor history and log access all disabled, the agent receives no home-data tools or Assist home-state context.

A timeout or failure after a successful earlier tool call cannot roll that action back. Check the device state before repeating a command. The integration performs no automatic inference retries.

## Development

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/ruff check custom_components scripts tests
.venv/bin/ruff format --check custom_components scripts tests
```

The sidebar frontend and its pinned Marked parser are bundled and served locally; there are no CDN imports or runtime downloads. The parser produces tokens, which an allowlist renders into safe DOM nodes. Run `npm run vendor:markdown` after deliberately updating the pinned parser; its MIT license is included. Browser checks use development-only Playwright: `npm ci`, `npx playwright install chromium`, then `npm run test:panel`. On WSL mounted Windows drives that disallow symlinks, use `npm ci --no-bin-links` and `node node_modules/playwright/cli.js install chromium`.

CI tests both Core versions; `requirements-dev-current.txt` provides the 2026.10.1 test environment. Tests verify OAuth rejection paths, signed JWT validation, grant permissions, import identity, refresh serialization, protected files, failed/incomplete SSE streams, protocol limits and real HA chat-log dispatch with the original user context, nested permission forms, revoked history permissions, and actual SQLite Recorder states/statistics including display-unit conversion. Automated network tests use mocked or local responses. Separately, live GPT-6.1 Sol text inference and a synthetic function-call round trip have passed; real HA device commands remain unverified. [Live verification checklist](docs/INSTALLATION.md#verify-your-installation) covers installation and exposure checks.

## Research sources

Checked against these official sources during implementation:

- [OpenAI: OSS ChatGPT plan usage](https://developers.openai.com/siwc/token-sharing-open-source)
- [OpenAI: registration, OAuth and PKCE](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [OpenAI: self-hosted credential transfer](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [OpenAI: model discovery and Responses inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [OpenAI: hosted web search and citations](https://developers.openai.com/api/docs/guides/tools-web-search)
- [OpenAI: preview API limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [OpenAI: refresh and revocation](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [Home Assistant: conversation entity API](https://developers.home-assistant.io/docs/core/entity/conversation/)
- [Home Assistant: LLM and Assist API boundaries](https://developers.home-assistant.io/docs/core/llm/)

MIT licensed. The accompanying open-source license is part of the intended OSS deployment.
