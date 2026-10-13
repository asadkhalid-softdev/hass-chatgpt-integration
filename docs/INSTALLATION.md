# Installation and account setup

## Requirements

- Home Assistant Core 2026.3.4 and 2026.10.1 are tested with Python 3.14. Other releases need compatibility verification.
- Administrator access to HA and its configuration directory.
- An eligible ChatGPT account/workspace that allows OSS plan sharing. Approval and model availability come from OpenAI; the integration cannot enable them.
- Python 3.12 or newer, or `uv`, on your Windows, Linux or macOS browser computer. The helper uses Unix private-file permissions or a protected Windows NTFS ACL. It does not need a Home Assistant access token.
- Internet access from that computer and HA to `auth.openai.com` and `api.openai.com` over HTTPS, with normal certificate verification.
- A secure HTTPS connection to your HA UI, such as your existing Home Assistant Cloud connection or correctly configured HTTPS. Do not submit credential JSON through an unencrypted remote HTTP connection.

## 1. Install the integration files

Back up your HA configuration. Copy the directory so that this exact file exists:

```text
/config/custom_components/chatgpt_assist/manifest.json
```

`/config` is the usual HA OS directory or the configuration volume mounted into HA Container. If you use a different config directory, use that path instead. Copy **only** the `chatgpt_assist` directory into `custom_components`, without another enclosing repository directory. Copy all its Python and translation files.

Restart Home Assistant. No `configuration.yaml` changes are needed. The integration uses JWT, cryptography and schema libraries already supplied by Home Assistant. It does not install separate pinned copies. For HACS, add `https://github.com/asadkhalid-softdev/hass-chatgpt-integration` under Custom repositories with type Integration, download ChatGPT Assist, then restart HA. If updating to 0.1.1 after the config-flow dependency error, use HACS Redownload to fetch the latest main branch and restart HA before trying Add integration again.

## 2. Complete ChatGPT OAuth on your browser's computer

Keep the entire repository available on this computer, including `scripts/` and `custom_components/`. The helper shares the integration's OAuth validation code.

With `uv`, run this **single line** from the repository directory. It works in PowerShell and Bash; the script declares its own dependencies and skips project discovery:

```text
uv run --python 3.12 --script scripts/chatgpt_login.py
```

The helper supports Python 3.12 or newer. Requesting 3.12 also works with older uv releases whose Python 3.14 downloads may still be prereleases. `uv` downloads the requested Python version if needed. See [uv's script documentation](https://docs.astral.sh/uv/guides/scripts/) for inline dependency handling.

If you prefer a virtual environment, install `scripts/requirements.txt` and run `scripts/chatgpt_login.py` with that environment's Python.

A browser opens the OpenAI authorization page. Sign in, select the intended workspace if requested, and authorize the app to use your ChatGPT plan. The page redirects to `http://127.0.0.1:<port>/auth/callback`. Return to the terminal and wait for **Sign-in verified**. The helper has a five-minute timeout and prints no tokens.

If the browser does not open:

```bash
uv run --python 3.12 --script scripts/chatgpt_login.py --no-browser
```

Open the printed URL in a browser on the **same computer**. In WSL, Windows-to-WSL localhost forwarding must work; if it does not, use a Linux/macOS desktop browser or fix forwarding. Do not run the helper inside the HA server or a remote SSH session unless the browser and callback listener share working loopback networking.

On Windows, use a local NTFS folder in your user profile, not a shared/FAT drive. The default account file is `%USERPROFILE%\.config\chatgpt-assist\chatgpt-account.json`. After sign-in, open it in PowerShell with:

```powershell
notepad "$HOME\.config\chatgpt-assist\chatgpt-account.json"
```

On Linux/macOS/WSL, the helper saves:

```text
~/.config/chatgpt-assist/chatgpt-account.json
~/.config/chatgpt-assist/chatgpt-account.host.json
```

The account file contains access, refresh and ID tokens. The host file holds a stable opaque host ID. Neither belongs in source control. Credentials must be imported while the access token is valid; if the import says they expired, sign in again.

For another account/workspace, use a distinct output path:

```bash
uv run --python 3.12 --script scripts/chatgpt_login.py --output ~/.config/chatgpt-assist/chatgpt-account-second.json
```

Running against an existing account file reauthorizes its saved registration. To create a different registration, choose a new output path. Never run two sign-in helpers against the same file simultaneously.

## 3. Import into Home Assistant

1. Access the HA UI over your secure HTTPS connection as an administrator.
2. Go to **Settings → Devices & services → Add integration**.
3. Search for **ChatGPT Assist**. If absent, verify the path, restart, and reload the browser.
4. Open the protected account JSON locally in a trusted editor, copy its complete contents, and paste into **Protected credential file JSON**. Submit.
5. Select one of the models returned for your ChatGPT account. Submit.
6. Clear your clipboard, close the credential editor, and keep any retained file in a private directory. Delete temporary transferred copies and disable clipboard history/sync for this transfer.

The field is masked, but masking is not encryption. The integration revalidates the signed access token before saving. HA keeps its own stable host ID; importing a laptop file cannot overwrite it. Copied sessions currently have the host-attribution limitations described in OpenAI's self-hosted guide.

After import, **HA must be the sole process refreshing this session**. The helper performs fresh authorization rather than refreshing the imported session. Keep the registration file protected if you retain it for future reauthorization.

## 4. Enable home access and choose the assistant

1. Open **Settings → Voice assistants → Expose** and expose only the devices/entities you intend the model to access. Start with one noncritical light.
2. Open the **ChatGPT Assist** integration's **Configure** options.
3. Enable **Allow reading and controlling exposed entities** and save. This also gives Assist's exposed home context to the model.
4. Under **Settings → Voice assistants**, add or edit an assistant. Select the **ChatGPT Assist** conversation agent. If you have several accounts, identify the correct integration entry/entity.
5. For voice, choose your speech-to-text and text-to-speech providers. This integration supplies the conversation agent only.
6. Choose that assistant in the Assist dialog or on your voice device. If commands must reach the model, review **Prefer handling commands locally**; enabling it may let HA handle ordinary commands without contacting ChatGPT.

The built-in Assist API performs supported intents, such as changing lights or supported temperatures. Administrative edits are outside its scope. An exposed script or scene can run its configured actions: review it carefully.

## Verify your installation

- With home access **off**, ask a general question and then a follow-up; confirm the answer retains context. Ask for a device action and verify nothing happens through this agent.
- Expose one test light and enable access. Ask its state, turn it on and then off, and check the real device state and HA's activity/logbook.
- Ask to control an **unexposed** entity. Verify the agent cannot resolve/control it through Assist. Exposure may include areas/scenes/scripts that indirectly control devices, so check those too.
- Ask for an ambiguous action. Confirm clarification before relying on it for important devices.
- Restart HA and ask another question to verify credentials survive restart.
- After access-token renewal, restart again and verify the rotated session survives.
- Revoke the app in ChatGPT Settings, then confirm model requests fail and HA offers reauthentication.

No real device/account verification was performed during development. Complete these checks before relying on this initial release.

## Reauthenticate or change accounts

Use the existing helper account file to reauthorize the **same** registration. Download HA diagnostics to find its nonsecret `host_id`, then use:

```bash
uv run --python 3.12 --script scripts/chatgpt_login.py --host-id urn:uuid:YOUR_HA_HOST_ID
```

Paste the resulting JSON in HA's reauthentication flow. A different signed account/client is rejected. To switch account/workspace, add a separate registration and integration entry and select its conversation agent. If the original registration file was lost, create a new registration and replace the old HA entry, then disconnect the old app in ChatGPT Settings.

## Usage, removal and troubleshooting

Review plan access and usage at [ChatGPT Settings → Usage](https://chatgpt.com/settings/usage). Plan-sharing limits can stop inference and are separate from API-key billing.

Remove the integration entry to delete local config credentials and its rotated-token store. Removal attempts session revocation; if it cannot confirm revocation, HA creates a notification asking you to disconnect the app in ChatGPT Settings. Uninstall the directory after removing entries and restart HA. Also delete any retained helper credential files when no longer needed.

| Problem | Check |
| --- | --- |
| Sign-in denied or plan permission missing | Authorize ChatGPT plan use; check account/workspace eligibility and policy. |
| Helper reports a token-verification failure | Share only the bracketed reason code (for example `audience_mismatch` or `nonce_mismatch`). Never share tokens or credential JSON. |
| Credentials rejected | Sign in again; import before access-token expiry; use the complete JSON and same registration for reauth. |
| No models available | OpenAI did not return eligible visible models for this account. Check workspace policy. |
| Usage limit or incomplete response | Version 0.1.6 reports a bracketed provider code. Share that code and the selected model; review ChatGPT Usage only when the code indicates a usage limit. Check device state before retrying. |
| Assistant cannot see a device | Enable home access, expose the entity, assign appropriate names/areas, and check Assist supports its intent. |
| Integration absent | Check `/config/custom_components/chatgpt_assist/manifest.json`, HA version, dependencies and restart. |
| `_Unsupported` serialization error with home access enabled | Update to 0.1.4 or newer through HACS, restart HA, and start a new Assist conversation. |
| OAuth localhost callback cannot connect | Run the helper on your browser's computer; check local firewall/WSL forwarding. |

Diagnostics include only model choice, access enabled, version and host ID. Do not share account files, `.storage` contents, HTTP traces or raw conversation logs.

## Automation and dashboard configuration

After installation, follow the [configuration administration guide](ADMINISTRATION.md) to enable exact targets, inspect automation triggers, prepare changes, and approve or restore them in Configure. Device control and configuration administration are separate permissions; configuration access starts disabled.

## Internet search

Version 0.3.0 adds an optional **Allow internet search** checkbox under **ChatGPT Assist → Configure → Model and permissions**. It starts disabled and uses your existing account connection. Follow the [internet search guide](WEB_SEARCH.md) for setup, live verification, privacy and unsupported-access recovery.
