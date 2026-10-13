/* ChatGPT Assist sidebar. Local assets only; messages never enter innerHTML. */
const PANEL_STYLE = `
:host{display:block;height:100%;height:100dvh;color:var(--primary-text-color,#172033);background:var(--primary-background-color,#f5f7fb);font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif)}
*{box-sizing:border-box}button,select,textarea{font:inherit}button{cursor:pointer}button:disabled{cursor:default;opacity:.45}button:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible,a:focus-visible{outline:3px solid var(--primary-color,#4465db);outline-offset:3px}
.shell{height:100%;display:flex;flex-direction:column}.header{display:flex;align-items:center;gap:12px;padding:14px 20px;border-bottom:1px solid var(--divider-color,#dde2ed);background:var(--card-background-color,#fff);flex-shrink:0}.heading{min-width:0;flex:1}.heading h1{font-size:18px;margin:0 0 3px;font-weight:650}.subtitle{color:var(--secondary-text-color,#667085);font-size:12px}.icon-button{border:0;background:transparent;color:inherit;border-radius:10px;padding:10px;font-size:20px;line-height:1}.icon-button:hover{background:var(--secondary-background-color,#eef1f7)}
.select-row{padding:10px 20px 0;max-width:900px;width:100%;margin:0 auto}.select-row label{display:flex;align-items:center;gap:12px;font-size:13px}.select-row select{padding:9px;border:1px solid var(--divider-color,#dde2ed);border-radius:9px;color:inherit;background:var(--card-background-color,#fff);min-width:0;flex:1}
details{position:relative}summary{list-style:none}summary::-webkit-details-marker{display:none}.menu-content{position:absolute;right:0;top:42px;width:210px;z-index:5;padding:6px;border:1px solid var(--divider-color,#dde2ed);border-radius:12px;background:var(--card-background-color,#fff);box-shadow:0 6px 24px #0002}.menu-content button{border:0;border-radius:8px;background:transparent;color:var(--error-color,#b42318);padding:12px;text-align:left;width:100%}.menu-content button:hover{background:var(--secondary-background-color,#eef1f7)}
.timeline{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;padding:24px 20px}.messages{width:100%;max-width:840px;margin:0 auto}.empty{min-height:220px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;color:var(--secondary-text-color,#667085);padding:30px 12px}.empty h2{font-size:24px;color:var(--primary-text-color,#172033);margin:10px 0}.empty p{max-width:440px;line-height:1.6;margin:4px 0}.empty .mark{font-size:32px;color:var(--primary-color,#4465db)}
.message{margin:0 0 24px;max-width:94%}.message.user{margin-left:auto;max-width:80%}.meta{font-size:12px;color:var(--secondary-text-color,#667085);margin:0 0 7px;display:flex;gap:10px;align-items:center}.user .meta{justify-content:flex-end}.bubble{line-height:1.65;overflow-wrap:anywhere;white-space:pre-wrap}.user .bubble{border-radius:16px 16px 4px 16px;padding:12px 16px;background:var(--primary-color,#4465db);color:var(--text-primary-color,#fff)}.assistant .bubble{border-radius:4px 16px 16px 16px;padding:15px 18px;background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#dde2ed)}.message.error .bubble{border-color:var(--error-color,#b42318);color:var(--error-color,#b42318)}.bubble p{margin:0 0 12px;white-space:pre-wrap}.bubble p:last-child{margin-bottom:0}.bubble a{color:var(--primary-color,#4465db);text-underline-offset:3px}.bubble pre{white-space:pre;overflow:auto;padding:12px;background:var(--secondary-background-color,#eef1f7);border-radius:8px;line-height:1.5}.bubble code{font-family:ui-monospace,monospace;font-size:.88em}.bubble :not(pre)>code{background:var(--secondary-background-color,#eef1f7);padding:2px 4px;border-radius:4px}.copy{margin-left:auto;padding:3px 6px;border:0;background:transparent;font-size:12px;color:inherit}.typing{display:flex;gap:5px;align-items:center}.typing span{width:6px;height:6px;background:var(--secondary-text-color,#667085);border-radius:50%;animation:pulse 1.3s infinite}.typing span:nth-child(2){animation-delay:.15s}.typing span:nth-child(3){animation-delay:.3s}.typing-label{font-size:13px;margin-left:8px;color:var(--secondary-text-color,#667085)}@keyframes pulse{0%,70%,100%{opacity:.3}35%{opacity:1}}
.alert{max-width:840px;width:calc(100% - 40px);margin:0 auto 8px;padding:10px 13px;background:var(--card-background-color,#fff);color:var(--error-color,#b42318);border-left:3px solid currentColor;border-radius:7px;font-size:13px;display:flex;align-items:center;gap:10px}.alert button{margin-left:auto;flex-shrink:0;border:0;background:transparent;text-decoration:underline;color:inherit;padding:6px}
.composer-wrap{flex-shrink:0;max-width:880px;width:100%;padding:0 20px max(14px,env(safe-area-inset-bottom));margin:0 auto}.composer{display:flex;gap:10px;align-items:flex-end;background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#dde2ed);border-radius:16px;padding:10px 12px;box-shadow:0 2px 8px #00006}.composer:focus-within{border-color:var(--primary-color,#4465db)}textarea{resize:none;width:100%;min-height:42px;max-height:150px;border:0;background:transparent;color:inherit;padding:9px 4px;line-height:1.5;outline:none!important}.send{border:0;border-radius:10px;min-height:40px;padding:9px 16px;background:var(--primary-color,#4465db);color:var(--text-primary-color,#fff);font-weight:600}.hint{display:flex;justify-content:space-between;color:var(--secondary-text-color,#667085);font-size:11px;gap:10px;margin:8px 4px 0}.hint a{color:inherit}
dialog{color:var(--primary-text-color,#172033);background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#dde2ed);border-radius:16px;max-width:430px;width:calc(100% - 32px);padding:24px;box-shadow:0 12px 70px #0004}dialog::backdrop{background:#0006}dialog h2{margin:0 0 12px;font-size:20px}dialog p{line-height:1.6;color:var(--secondary-text-color,#667085)}.dialog-actions{display:flex;gap:10px;justify-content:flex-end;margin-top:24px}.dialog-actions button{border:0;border-radius:8px;padding:10px 16px;background:var(--secondary-background-color,#eef1f7);color:inherit}.dialog-actions .danger{background:var(--error-color,#b42318);color:#fff}
[hidden]{display:none!important}@media(max-width:600px){.header{padding:10px 12px}.timeline{padding:20px 12px}.composer-wrap{padding-left:12px;padding-right:12px}.message{max-width:100%}.message.user{max-width:90%}.select-row{padding-left:12px;padding-right:12px}.alert{width:calc(100% - 24px)}.hint{font-size:10px}.heading h1{font-size:17px}}@media(prefers-reduced-motion:reduce){.typing span{animation:none}}
`;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function safeLink(value) {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

function inlineText(parent, text) {
  const expression = /\[([^\]\n]+)\]\((?:<([^>\n]+)>|([^\s)]+))\)|`([^`\n]+)`|\*\*([^*\n]+)\*\*/g;
  let cursor = 0;
  for (const match of text.matchAll(expression)) {
    parent.append(document.createTextNode(text.slice(cursor, match.index)));
    if (match[1]) {
      const href = safeLink(match[2] || match[3]);
      if (href) {
        const link = node("a", match[1]);
        link.href = href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        parent.append(link);
      } else parent.append(document.createTextNode(match[0]));
    } else parent.append(node(match[4] ? "code" : "strong", match[4] || match[5]));
    cursor = match.index + match[0].length;
  }
  parent.append(document.createTextNode(text.slice(cursor)));
}

function messageBody(text) {
  const body = node("div", undefined, "bubble");
  const lines = text.split("\n");
  let paragraph = [], code = [], fence = null;
  const flush = () => {
    if (!paragraph.length) return;
    const part = node("p");
    inlineText(part, paragraph.join("\n"));
    body.append(part);
    paragraph = [];
  };
  for (const line of lines) {
    if (fence) {
      if (line.startsWith(fence)) {
        const pre = node("pre");
        pre.append(node("code", code.join("\n")));
        body.append(pre);
        fence = null; code = [];
      } else code.push(line);
    } else if (/^`{3,}/.test(line)) {
      flush(); fence = line.match(/^`+/)[0];
    } else if (!line.trim()) flush();
    else paragraph.push(line);
  }
  if (fence) { const pre = node("pre"); pre.append(node("code", code.join("\n"))); body.append(pre); }
  flush();
  return body;
}

class ChatGPTAssistPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._messages = [];
    this._agents = [];
    this._entryId = null;
    this._busy = false;
    this._ready = false;
    this._generation = 0;
  }

  set hass(value) {
    const oldUser = this._ownerId;
    const oldConnection = this._hass?.connection;
    this._hass = value;
    this._ownerId = value.user?.id;
    if (!this._built) this._build();
    if (!this._started || oldUser !== value.user?.id || oldConnection !== value.connection) {
      this._started = true;
      this._generation++;
      this._messages = [];
      this._entryId = null;
      this._busy = false;
      this._ready = false;
      this._agents = [];
      this._select.replaceChildren();
      this._selectRow.hidden = true;
      this._settingsLink.hidden = !value.user?.is_admin;
      this._input.value = "";
      this._menu.open = false;
      if (this._dialog.open) this._dialog.close();
      this._alert.hidden = true;
      clearTimeout(this._pollTimer);
      this._renderMessages();
      this._initialize();
    }
  }

  connectedCallback() { if (!this._built) this._build(); else if (this._hass && this._started) this._initialize(); }

  _build() {
    this._built = true;
    const root = this.shadowRoot;
    root.append(node("style", PANEL_STYLE));
    const shell = node("div", undefined, "shell");
    const header = node("header", undefined, "header");
    const sidebar = node("button", "☰", "icon-button");
    sidebar.type = "button";
    sidebar.setAttribute("aria-label", "Open Home Assistant sidebar");
    sidebar.onclick = () => this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
    const heading = node("div", undefined, "heading");
    heading.append(node("h1", "ChatGPT Assist"));
    this._subtitle = node("div", "Connecting…", "subtitle");
    heading.append(this._subtitle);
    this._menu = node("details");
    const summary = node("summary", "⋮", "icon-button");
    summary.setAttribute("aria-label", "Chat options");
    const menuContent = node("div", undefined, "menu-content");
    this._clearButton = node("button", "Clear message history");
    this._clearButton.type = "button";
    this._clearButton.onclick = () => { this._menu.open = false; this._dialog.showModal(); };
    menuContent.append(this._clearButton);
    this._menu.append(summary, menuContent);
    header.append(sidebar, heading, this._menu);
    this._selectRow = node("div", undefined, "select-row");
    const label = node("label", "Assistant");
    this._select = node("select");
    this._select.setAttribute("aria-label", "Choose assistant");
    this._select.onchange = () => {
      this._entryId = this._select.value;
      this._input.value = "";
      this._messages = [];
      this._renderMessages();
      this._loadHistory();
    };
    label.append(this._select);
    this._selectRow.append(label);
    this._timeline = node("section", undefined, "timeline");
    this._timeline.setAttribute("aria-label", "Conversation messages");
    this._list = node("div", undefined, "messages");
    this._list.setAttribute("role", "log");
    this._list.setAttribute("aria-live", "polite");
    this._list.setAttribute("aria-relevant", "additions text");
    this._timeline.append(this._list);
    this._alert = node("div", undefined, "alert");
    this._alert.setAttribute("role", "alert");
    this._alert.hidden = true;
    this._alertText = node("span");
    const refresh = node("button", "Refresh chat");
    refresh.type = "button";
    refresh.onclick = () => this._initialize();
    this._alert.append(this._alertText, refresh);
    const composerWrap = node("div", undefined, "composer-wrap");
    const form = node("form", undefined, "composer");
    form.onsubmit = (event) => { event.preventDefault(); this._send(); };
    this._input = node("textarea");
    this._input.placeholder = "Message ChatGPT Assist…";
    this._input.rows = 1;
    this._input.maxLength = 4000;
    this._input.setAttribute("aria-label", "Your message");
    this._input.oninput = () => {
      this._input.style.height = "auto";
      this._input.style.height = `${Math.min(this._input.scrollHeight, 150)}px`;
      this._updateControls();
    };
    this._input.onkeydown = (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
        event.preventDefault();
        this._send();
      }
    };
    this._sendButton = node("button", "Send", "send");
    this._sendButton.type = "submit";
    form.append(this._input, this._sendButton);
    const hint = node("div", undefined, "hint");
    hint.append(node("span", "Enter to send · Shift+Enter for a new line"));
    this._settingsLink = node("a", "Settings & review");
    this._settingsLink.href = "/config/integrations/integration/chatgpt_assist";
    hint.append(this._settingsLink);
    composerWrap.append(form, hint);
    this._dialog = node("dialog");
    this._dialog.setAttribute("aria-labelledby", "clear-title");
    const title = node("h2", "Clear message history?"); title.id = "clear-title";
    const actions = node("div", undefined, "dialog-actions");
    const cancel = node("button", "Cancel"); cancel.type = "button"; cancel.onclick = () => this._dialog.close();
    const confirm = node("button", "Clear history", "danger"); confirm.type = "button"; confirm.onclick = () => this._clear();
    actions.append(cancel, confirm);
    this._dialog.append(title, node("p", "This removes your saved messages for this assistant and resets its conversation context. It cannot be undone."), actions);
    shell.append(header, this._selectRow, this._timeline, this._alert, composerWrap, this._dialog);
    root.append(shell);
    this._renderMessages();
    this._updateControls();
  }

  _rpc(operation, data = {}) {
    return this._hass.callWS({ type: "chatgpt_assist/sidebar", operation, ...data });
  }

  async _initialize() {
    const generation = ++this._generation;
    this._ready = false;
    this._updateControls();
    try {
      const result = await this._rpc("agents");
      if (generation !== this._generation) return;
      this._agents = result.agents;
      this._select.replaceChildren();
      for (const agent of this._agents) { const option = node("option", agent.title); option.value = agent.entry_id; this._select.append(option); }
      if (!this._agents.some((agent) => agent.entry_id === this._entryId)) this._entryId = this._agents[0]?.entry_id || null;
      this._selectRow.hidden = this._agents.length < 2;
      this._settingsLink.hidden = !this._hass.user?.is_admin;
      this._select.value = this._entryId || "";
      if (this._entryId) await this._loadHistory();
      else { this._messages = []; this._ready = true; this._renderMessages(); this._updateControls(); }
    } catch (error) { if (generation === this._generation) this._showError(error, "Could not load assistants."); }
  }

  async _loadHistory() {
    const generation = ++this._generation;
    const entryId = this._entryId;
    this._ready = false;
    this._updateControls();
    try {
      const result = await this._rpc("history", { entry_id: entryId });
      if (generation !== this._generation || entryId !== this._entryId) return;
      this._messages = result.messages;
      this._busy = result.busy;
      this._ready = true;
      this._alert.hidden = true;
      this._renderMessages();
      this._updateControls();
      if (this._busy) this._pollHistory();
    } catch (error) { if (generation === this._generation) this._showError(error, "Could not load this chat."); }
  }

  _pollHistory() {
    clearTimeout(this._pollTimer);
    this._pollTimer = setTimeout(() => { if (this.isConnected && this._busy) this._loadHistory(); }, 1500);
  }

  async _send() {
    const text = this._input.value.trim();
    if (!text || this._busy || !this._ready || !this._entryId) return;
    const generation = this._generation;
    const entryId = this._entryId;
    const requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    this._busy = true;
    this._alert.hidden = true;
    this._input.value = "";
    this._input.style.height = "auto";
    this._messages.push({ role: "user", content: text, time: Date.now() / 1000 }, { role: "assistant", content: "", status: "pending", time: Date.now() / 1000 });
    this._renderMessages(true);
    this._updateControls();
    try {
      const result = await this._rpc("send", { entry_id: entryId, text, request_id: requestId, language: this._hass.language || "en" });
      if (generation !== this._generation || entryId !== this._entryId) return;
      this._messages = result.messages;
      this._busy = result.busy;
      this._renderMessages();
      this._updateControls();
      this._input.focus();
    } catch (error) {
      if (generation !== this._generation) return;
      this._busy = false;
      this._ready = false;
      this._showError(error, "The connection was interrupted. Your message may have completed; refresh chat and check device state before retrying.");
    }
  }

  async _clear() {
    if (this._busy || !this._entryId) return;
    this._dialog.close();
    const generation = this._generation;
    this._ready = false;
    this._updateControls();
    try {
      const result = await this._rpc("clear", { entry_id: this._entryId });
      if (generation !== this._generation) return;
      this._messages = result.messages;
      this._busy = false;
      this._ready = true;
      this._input.value = "";
      this._alert.hidden = true;
      this._renderMessages();
      this._updateControls();
      this._input.focus();
    } catch (error) { this._showError(error, "Could not clear history."); }
  }

  _showError(error, fallback) {
    this._alertText.textContent = error?.message || fallback;
    this._alert.hidden = false;
    this._updateControls();
  }

  _updateControls() {
    const available = this._ready && Boolean(this._entryId);
    this._sendButton.disabled = !available || this._busy || !this._input.value.trim();
    this._clearButton.disabled = !available || this._busy || !this._messages.length;
    this._select.disabled = this._busy;
    this._input.disabled = !available;
    const agent = this._agents.find((item) => item.entry_id === this._entryId);
    this._subtitle.textContent = !this._ready ? "Connecting…" : this._busy ? "Replying…" : agent ? [agent.model, agent.web_search ? "Internet search enabled" : null].filter(Boolean).join(" · ") : "No assistant available";
  }

  _renderMessages(forceScroll = false) {
    const nearBottom = this._timeline.scrollHeight - this._timeline.scrollTop - this._timeline.clientHeight < 100;
    this._list.replaceChildren();
    if (!this._messages.length) {
      const empty = node("div", undefined, "empty");
      empty.append(node("div", "✦", "mark"), node("h2", this._entryId ? "How can I help?" : "Welcome to ChatGPT Assist"), node("p", this._entryId ? "Ask about your home, get an answer, or look something up. Your assistant uses the permissions you configured." : "Configure a ChatGPT Assist account to start chatting. Assistants with configuration access require an administrator."));
      if (!this._entryId && this._hass) { const refresh = node("button", "Refresh assistants", "icon-button"); refresh.type = "button"; refresh.style.fontSize = "13px"; refresh.onclick = () => this._initialize(); empty.append(refresh); }
      if (this._hass?.user?.is_admin && !this._entryId) { const link = node("a", "Open integration settings"); link.href = "/config/integrations/integration/chatgpt_assist"; empty.append(link); }
      this._list.append(empty);
    }
    for (const message of this._messages) {
      const article = node("article", undefined, `message ${message.role}${message.status === "error" ? " error" : ""}`);
      const meta = node("div", undefined, "meta");
      meta.append(node("span", message.role === "user" ? "You" : "ChatGPT Assist"));
      if (message.time) { const time = node("time", new Date(message.time * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })); time.dateTime = new Date(message.time * 1000).toISOString(); meta.append(time); }
      article.append(meta);
      if (message.status === "pending") {
        const bubble = node("div", undefined, "bubble typing");
        bubble.setAttribute("role", "status");
        for (let index = 0; index < 3; index++) bubble.append(node("span"));
        bubble.append(node("div", "Thinking…", "typing-label"));
        article.append(bubble);
      } else if (message.role === "user") article.append(node("div", message.content, "bubble"));
      else {
        article.append(messageBody(message.content));
        if (navigator.clipboard) { const copy = node("button", "Copy", "copy"); copy.type = "button"; copy.setAttribute("aria-label", "Copy assistant response"); copy.onclick = async () => { try { await navigator.clipboard.writeText(message.content); copy.textContent = "Copied"; } catch { copy.textContent = "Copy unavailable"; } }; meta.append(copy); }
      }
      this._list.append(article);
    }
    if (nearBottom || forceScroll) requestAnimationFrame(() => { this._timeline.scrollTop = this._timeline.scrollHeight; });
  }

  disconnectedCallback() { clearTimeout(this._pollTimer); }
}

if (!customElements.get("chatgpt-assist-panel")) customElements.define("chatgpt-assist-panel", ChatGPTAssistPanel);
