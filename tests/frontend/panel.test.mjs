import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { chromium } from "playwright";

let browser, server, origin;
before(async () => {
  await mkdir("test-results", {recursive: true});
  const script = await readFile(new URL("../../custom_components/chatgpt_assist/frontend/panel.js", import.meta.url));
  server = createServer((request, response) => {
    if (request.url === "/panel.js") { response.writeHead(200, {"Content-Type": "text/javascript"}); response.end(script); }
    else { response.writeHead(200, {"Content-Type": "text/html"}); response.end('<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>html,body{margin:0;height:100%;font-family:system-ui}</style></head><body><script type="module" src="/panel.js"></script></body></html>'); }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true });
});
after(async () => { await browser?.close(); await new Promise((resolve) => server?.close(resolve)); });

async function fixture(width = 1200, messages = []) {
  const page = await browser.newPage({ viewport: { width, height: 800 } });
  await page.goto(origin);
  await page.waitForFunction(() => customElements.get("chatgpt-assist-panel"));
  await page.evaluate((history) => {
    window.sent = [];
    window.historyMessages = history;
    window.blockReply = false;
    const element = document.createElement("chatgpt-assist-panel");
    document.body.append(element);
    element.hass = {
      user: { id: "user-one", is_admin: true }, language: "en", connection: {},
      callWS: async (message) => {
        window.sent.push(message);
        if (message.operation === "agents") return {agents: [{entry_id: "account", title: "My ChatGPT", model: "GPT-6.1 Sol", web_search: true}]};
        if (message.operation === "history") return {messages: window.historyMessages, busy: false};
        if (message.operation === "clear") { window.historyMessages = []; return {messages: [], busy: false}; }
        if (message.operation === "send") {
          window.historyMessages.push({role: "user", content: message.text, time: Date.now()/1000});
          if (window.blockReply) await new Promise((resolve) => { window.finishReply = resolve; });
          window.historyMessages.push({role: "assistant", content: "An answer with a citation. [1](<https://example.com/news>)", time: Date.now()/1000});
          return {messages: window.historyMessages, busy: false};
        }
      }
    };
  }, messages);
  await page.waitForFunction(() => document.querySelector("chatgpt-assist-panel")._ready);
  return page;
}

test("Enter sends once; Shift+Enter and IME preserve composing text", async () => {
  const page = await fixture();
  try {
    const input = page.getByRole("textbox", {name: "Your message"});
    await input.fill("First line");
    await input.press("Shift+Enter");
    await input.press("a");
    assert.equal(await input.inputValue(), "First line\na");
    assert.equal(await page.evaluate(() => sent.filter((item) => item.operation === "send").length), 0);
    await input.dispatchEvent("keydown", {key: "Enter", isComposing: true});
    assert.equal(await page.evaluate(() => sent.filter((item) => item.operation === "send").length), 0);
    await input.press("Enter");
    await page.waitForFunction(() => !document.querySelector("chatgpt-assist-panel")._busy);
    assert.equal(await page.evaluate(() => sent.filter((item) => item.operation === "send").length), 1);
    assert.equal(await input.inputValue(), "");
    assert.equal(await page.getByRole("link", {name: "1", exact: true}).getAttribute("href"), "https://example.com/news");
    assert.equal(await page.getByRole("button", {name: /new conversation/i}).count(), 0);
  } finally { await page.close(); }
});

test("history renders safely and menu clear requires confirmation", async () => {
  const page = await fixture(1200, [
    {role: "user", content: "Previous question", time: 1700000000},
    {role: "assistant", content: '<img src=x onerror="window.pwned=true">\n\n[unsafe](javascript:alert(1))\n\n```yaml\nalias: Example\n```', time: 1700000001}
  ]);
  try {
    assert.equal(await page.locator("chatgpt-assist-panel .bubble img").count(), 0);
    assert.equal(await page.getByRole("link", {name: "unsafe"}).count(), 0);
    assert.match(await page.locator("chatgpt-assist-panel pre").textContent(), /alias: Example/);
    await page.getByLabel("Chat options").click();
    await page.getByRole("button", {name: "Clear message history"}).click();
    await page.getByRole("button", {name: "Cancel", exact: true}).click();
    assert.equal(await page.evaluate(() => sent.filter((item) => item.operation === "clear").length), 0);
    await page.getByLabel("Chat options").click();
    await page.getByRole("button", {name: "Clear message history"}).click();
    await page.getByRole("button", {name: "Clear history", exact: true}).click();
    await page.waitForFunction(() => document.querySelector("chatgpt-assist-panel")._messages.length === 0);
    assert.equal(await page.evaluate(() => sent.filter((item) => item.operation === "clear").length), 1);
    assert.equal(await page.evaluate(() => window.pwned), undefined);
  } finally { await page.close(); }
});

test("mobile layout, pending state and duplicate-submit prevention", async () => {
  const page = await fixture(390);
  try {
    await page.evaluate(() => { window.blockReply = true; });
    const input = page.getByRole("textbox", {name: "Your message"});
    await input.fill("Turn on the kitchen light");
    await input.press("Enter");
    await page.waitForFunction(() => window.finishReply);
    assert.equal(await page.getByText("Thinking…", {exact: true}).count(), 1);
    await input.fill("Next message");
    await input.press("Enter");
    assert.equal(await page.evaluate(() => sent.filter((item) => item.operation === "send").length), 1);
    await page.getByLabel("Chat options").click();
    assert.equal(await page.getByRole("button", {name: "Clear message history"}).isDisabled(), true);
    await page.getByLabel("Chat options").click();
    const bounds = await input.boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 390);
    await page.screenshot({path: process.env.PANEL_MOBILE_SCREENSHOT || "/tmp/chatgpt-assist-mobile.png", fullPage: true});
    await page.evaluate(() => window.finishReply());
    await page.waitForFunction(() => !document.querySelector("chatgpt-assist-panel")._busy);
    assert.equal(await input.inputValue(), "Next message");
  } finally { await page.close(); }
});

test("desktop chat survives reopening and account identity changes clear visible state", async () => {
  const page = await fixture(1280, [{role: "user", content: "Read my automation", time: 1700000000}, {role: "assistant", content: "**Morning lights** starts at 07:00.\n\nRead the documentation. [1](<https://www.home-assistant.io/docs/automation/>)", time: 1700000001}]);
  try {
    await page.screenshot({path: process.env.PANEL_DESKTOP_SCREENSHOT || "/tmp/chatgpt-assist-desktop.png", fullPage: true});
    await page.evaluate(() => {
      const element = document.querySelector("chatgpt-assist-panel");
      element.remove(); document.body.append(element);
    });
    await page.waitForFunction(() => document.querySelector("chatgpt-assist-panel")._ready);
    assert.match(await page.locator("chatgpt-assist-panel .messages").textContent(), /Morning lights/);
    await page.evaluate(() => {
      const element = document.querySelector("chatgpt-assist-panel");
      window.historyMessages = [];
      element.hass = {...element._hass, user: {id: "another-user", is_admin: false}};
    });
    await page.waitForFunction(() => document.querySelector("chatgpt-assist-panel")._ready);
    assert.doesNotMatch(await page.locator("chatgpt-assist-panel .messages").textContent(), /Morning lights/);
    assert.equal(await page.getByRole("link", {name: "Settings & review"}).isVisible(), false);
  } finally { await page.close(); }
});

test("identity switch clears visible private content and draft before network response", async () => {
  const page = await fixture(1200, [{role: "assistant", content: "Private administrator configuration", time: 1700000000}]);
  try {
    await page.getByRole("textbox", {name: "Your message"}).fill("Private draft");
    await page.evaluate(() => {
      const element = document.querySelector("chatgpt-assist-panel");
      element.hass = {...element._hass, user: {id: "guest", is_admin: false}, callWS: () => new Promise(() => {})};
    });
    assert.doesNotMatch(await page.locator("chatgpt-assist-panel .messages").textContent(), /Private/);
    assert.equal(await page.getByRole("textbox", {name: "Your message"}).inputValue(), "");
    assert.equal(await page.getByRole("textbox", {name: "Your message"}).isDisabled(), true);
  } finally { await page.close(); }
});
