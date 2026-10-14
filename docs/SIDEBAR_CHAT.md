# Sidebar chat

Version 0.4.0 adds **ChatGPT Assist** to the Home Assistant sidebar. The frontend is bundled with the integration; no separate HACS dashboard card, external scripts or additional sign-in is needed.

## Open the chat

1. Push the update, then update/redownload **ChatGPT Assist** in HACS.
2. Restart Home Assistant and refresh your browser tab.
3. Click **ChatGPT Assist** in the sidebar. Its direct path is `/chatgpt-assist`.
4. If you have multiple available account registrations, select the assistant above the messages. The most recently used assistant is offered first after a page reload.

The panel uses your existing ChatGPT conversation agent, model and permissions. The header indicates administrator log access and direct automation updates when available. Direct automation mode can apply requested changes without a separate dialog; dashboard changes still require Configure review. Assist and voice pipelines continue to work. Selecting an assistant switches to that account’s own history; it does not send a message. If no assistant is available, use **Refresh assistants** or check the integration settings. Assistants with configuration administration enabled are available only to authenticated administrators.

## Send messages

- **Enter** sends the message.
- **Shift+Enter** inserts a new line.
- The **Send** button also sends.
- IME composition does not send prematurely.
- A reply indicator appears while the assistant is working. You can draft the next message, but another send and history clearing are blocked until the current reply finishes.

Version 0.5.2 renders GitHub Flavored Markdown: real tables with headers and aligned columns, headings, nested numbered/bulleted lists, read-only task lists, block quotes, horizontal rules, bold/italic/strikethrough text, inline code, fenced code blocks with language labels, and source links. Wide tables scroll inside the message on mobile and can be focused for keyboard scrolling. This is a local Markdown renderer, not ChatGPT’s proprietary frontend. Mathematical notation, Mermaid diagrams and syntax highlighting are not included. Source links open in a separate tab; message HTML and images are treated as text rather than executed or fetched. Use **Copy** to copy an assistant response.

Internet search is controlled by **Allow internet search** in Configure. Direct automation mode can apply requested updates and restore their backups from chat. Dashboard proposals and manual-mode automation proposals require **Configure → Review changes**; the chat provides a settings/review link for administrators. Log access is administrator-only and can be disabled independently.

## Message history

History belongs to your Home Assistant user and the selected account. It is saved on HA, not in browser local storage, so refreshing the page or reopening the sidebar restores it. Native model/tool context is restored after HA’s normal chat-session expiry or a restart, preserving recent follow-ups without replaying old actions.

Up to 60 displayed messages are retained, within a 128 KB budget; older messages are removed in user/assistant pairs. Native context is separately bounded to 160 KB and trimmed at whole-turn boundaries. Very long answers are shortened in the sidebar. Ask for a smaller section when needed. Other open tabs refresh their chat view when reopened or refreshed.

## Clear history

Open the **⋮** menu at the top right, choose **Clear message history**, and confirm **Clear history**.

This removes your saved messages and resets the model’s active conversation context for the selected assistant. The other accounts and other HA users’ chats remain intact. There is no New conversation button; clearing history is how you reset this chat. Wait for an active reply to finish before clearing.

Clearing chat history does not delete Home Assistant’s separate traces, backup copies, pending configuration proposals or data retained by OpenAI. Removing a ChatGPT Assist integration entry removes the histories associated with that entry.

## Connection and access errors

If a connection drops, the message may still finish on HA. Use **Refresh chat** and check device state before sending the instruction again. The panel does not automatically retry a message; recent request IDs prevent duplicate delivery. Interrupted replies are marked as errors rather than silently resent.

If administration is enabled, or your history contains administrator configuration data from an earlier session, an active administrator is required to access it. An account without that permission cannot read that history through the sidebar API. Settings changes that invalidate older configuration context may require clearing that chat.

## Privacy and verification

The panel communicates over HA’s authenticated WebSocket and never receives your OAuth credentials. Its private history store is `.storage/chatgpt_assist.sidebar_history`; secure your HA host and backups because private storage is not encryption. The selected agent sends conversation context to OpenAI as usual. Internet search has its own privacy considerations described in the [search guide](WEB_SEARCH.md).

Backend checks run against Core 2026.3.4 and 2026.10.1. Chromium tests cover desktop/mobile rendering, Enter/Shift+Enter, history, clear confirmation, source links, safe rendering, pending replies and identity changes. The browser tests use an isolated HA API fixture; verify the sidebar on your actual installation after updating.
