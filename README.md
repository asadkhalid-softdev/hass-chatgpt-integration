# ChatGPT Assist for Home Assistant

A custom conversation integration that signs in with your **ChatGPT account** and uses eligible account models in Home Assistant Assist. Device access is opt-in and uses Home Assistant's built-in Assist API.

**Status:** initial release, tested against Home Assistant Core **2026.3.4** and **2026.10.1**, Python **3.14**. OAuth and inference follow the documented OpenAI OSS preview. Live GPT-6.1 Sol text inference and a synthetic function-call round trip have been verified. Your account eligibility and a real home installation still require your verification. Other Home Assistant versions have not been verified. This is an independent project, not an official OpenAI or Home Assistant integration.

## What it does

- Inspect automation triggers/conditions/actions and dashboard configuration, prepare drafts, and apply or restore them through an administrator review form when separately enabled.
- Discover models available to the authorized ChatGPT account.
- Answer questions in Assist and retain conversation context through Home Assistant's chat log.
- Read live home information and control exposed entities when you enable device access: for example lights, supported thermostat settings, and exposed scenes/scripts.
- Validate OAuth state, PKCE, ID-token signatures, issuer, audience, expiry and nonce. Verify signed access-token identity again on import.
- Renew tokens with serialized, atomic storage of rotating refresh tokens; provide reauthentication when a session is revoked.
- Bound each request to 8 sequential tool calls and 180 seconds. Validate tool names, namespaces, argument schemas and duplicate call IDs before executing a response.

Optional [configuration administration](docs/ADMINISTRATION.md) can inspect and draft changes to explicitly allowed UI-managed automations and existing storage dashboards. Each change requires administrator review in Configure, with validation, conflict checks and a saved backup. This includes creating automations under IDs you explicitly allow. Package/YAML dashboard editing, integration installation, arbitrary services and shell access are unsupported.

## Why sign-in uses a helper

OpenAI documents dynamic OAuth registration for open-source, locally hosted clients, including eligible ChatGPT plan inference. It requires a `127.0.0.1` browser callback. That callback reaches your browser's computer, whereas Home Assistant commonly runs elsewhere. The included helper completes OAuth locally and produces a private credential file, following OpenAI's documented self-hosted transfer procedure. You import that file into HA over a secure connection; HA then owns refreshes.

There is no client secret to obtain, no borrowed Codex client ID, no ChatGPT browser-cookie extraction and no private `backend-api` endpoint. The general commercial partner sign-in program has separate availability requirements. The OSS flow is a preview: account/workspace policy, plan permissions and usage limits determine availability. If OpenAI does not enable it for your account, this integration cannot bypass that restriction. Use HA's official **OpenAI Conversation** integration with an API key if you need that alternative; its billing is separate from ChatGPT plan use.

## Install

Full instructions: [Installation guide](docs/INSTALLATION.md).

1. Copy `custom_components/chatgpt_assist` into your HA configuration's `custom_components/` directory, then restart HA.
2. On your browser's computer, run this single line in PowerShell or Bash with `uv` installed. The helper manages its own dependencies:

   ```text
   uv run --python 3.12 --script scripts/chatgpt_login.py
   ```

3. Open HA over HTTPS → **Settings → Devices & services → Add integration → ChatGPT Assist**. Paste the protected JSON credential file, then choose a model.
4. Review exposed entities under **Settings → Voice assistants → Expose**. Enable device access in the integration's options only when ready.
5. Edit or add an assistant under **Settings → Voice assistants** and select the new **ChatGPT Assist** conversation agent. Speech recognition and text-to-speech are configured separately.

You can add multiple account/workspace registrations by using separate helper output files and adding separate integration entries. The integration title uses an issued client-ID suffix to distinguish registrations. Removing an entry attempts remote session revocation and removes its local rotated-token store.

## Security and privacy

See [Security model](SECURITY.md). Your questions, conversation context and Assist's exposed home context are sent to OpenAI. `store=false` avoids Responses application storage; it does not promise zero provider retention. This flow grants no access to your ChatGPT chat history. Home Assistant owns its chat logs and storage policies.

Tokens are sensitive secrets. The helper writes owner-only files on Unix and protected files accessible to the current account on Windows NTFS. HA stores initial credentials in its normal config-entry storage and renewed credentials in a dedicated atomic `.storage` record, **not an encrypted vault**. Secure your HA host and backups, access the UI over HTTPS, and revoke the app in ChatGPT Settings if credentials leak. Do not turn on broad HTTP/debug logging or include credential files in bug reports.

A model can misunderstand requests or follow malicious device text. Exposure is the primary permission boundary. Avoid exposing door locks, alarms and powerful scripts until you have assessed the consequences. Assist device actions have no per-action confirmation UI or separate read-only mode. Configuration edits use a separate mandatory review form. With both device and configuration access disabled, the agent receives neither Assist tools nor Assist's home-state context.

A timeout or failure after a successful earlier tool call cannot roll that action back. Check the device state before repeating a command. The integration performs no automatic inference retries.

## Development

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/ruff check custom_components scripts tests
.venv/bin/ruff format --check custom_components scripts tests
```

CI tests both Core versions; `requirements-dev-current.txt` provides the 2026.10.1 test environment. Tests verify OAuth rejection paths, signed JWT validation, grant permissions, import identity, refresh serialization, protected files, failed/incomplete SSE streams, protocol limits and real HA chat-log dispatch with the original user context. Automated network tests use mocked or local responses. Separately, live GPT-6.1 Sol text inference and a synthetic function-call round trip have passed; real HA device commands remain unverified. [Live verification checklist](docs/INSTALLATION.md#verify-your-installation) covers installation and exposure checks.

## Research sources

Checked against these official sources during implementation:

- [OpenAI: OSS ChatGPT plan usage](https://developers.openai.com/siwc/token-sharing-open-source)
- [OpenAI: registration, OAuth and PKCE](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [OpenAI: self-hosted credential transfer](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [OpenAI: model discovery and Responses inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [OpenAI: preview API limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [OpenAI: refresh and revocation](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [Home Assistant: conversation entity API](https://developers.home-assistant.io/docs/core/entity/conversation/)
- [Home Assistant: LLM and Assist API boundaries](https://developers.home-assistant.io/docs/core/llm/)

MIT licensed. The accompanying open-source license is part of the intended OSS deployment.
