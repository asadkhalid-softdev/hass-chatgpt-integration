import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { chromium } from "playwright";

let browser, server, origin;
before(async () => {
  await mkdir("test-results", {recursive: true});
  const script = await readFile(new URL("../../custom_components/chatgpt_assist/frontend/panel.js", import.meta.url));
  const markdown = await readFile(new URL("../../custom_components/chatgpt_assist/frontend/vendor/marked.js", import.meta.url));
  server = createServer((request, response) => {
    if (request.url.startsWith("/vendor/marked.js")) { response.writeHead(200, {"Content-Type": "text/javascript"}); response.end(markdown); }
    else if (request.url === "/panel.js") { response.writeHead(200, {"Content-Type": "text/javascript"}); response.end(script); }
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

test("GFM tables and rich Markdown render semantically with safe nested content", async () => {
  const content = [
    "## Temperature report", "", "| Sensor | Average | Note |", "| :--- | ---: | :---: |",
    "| **Bedroom** | 20.5 °C | [Source](https://example.com/data) |",
    "| Kitchen | 21 °C | escaped \\| pipe |", "",
    "1. First step", "   - Nested *detail* with ~~old~~ text", "2. Second step", "",
    "- [x] Completed", "- [ ] Pending", "", "> **Summary:** stable &amp; comfortable.", "",
    "---", "", "```yaml", "alias: Example", "# <script> is literal code", "```"
  ].join("\n");
  const page = await fixture(1200, [{role: "assistant", content, time: 1700000000}]);
  try {
    assert.equal(await page.getByRole("heading", {name: "Temperature report"}).count(), 1);
    assert.equal(await page.getByRole("table").count(), 1);
    assert.equal(await page.getByRole("columnheader").count(), 3);
    assert.equal(await page.getByRole("row").count(), 3);
    assert.equal(await page.getByRole("cell", {name: "escaped | pipe", exact: true}).count(), 1);
    assert.equal(await page.getByRole("columnheader", {name: "Average"}).evaluate((el) => getComputedStyle(el).textAlign), "right");
    assert.equal(await page.locator("chatgpt-assist-panel ol > li ul > li em").textContent(), "detail");
    assert.equal(await page.locator("chatgpt-assist-panel del").textContent(), "old");
    assert.match(await page.locator("chatgpt-assist-panel blockquote").textContent(), /stable & comfortable/);
    assert.equal(await page.getByRole("checkbox", {name: "Completed task"}).isChecked(), true);
    assert.equal(await page.getByRole("checkbox", {name: "Incomplete task"}).isDisabled(), true);
    assert.doesNotMatch(await page.locator("chatgpt-assist-panel .bubble").textContent(), /\[x\]|\[ \]/);
    assert.equal(await page.locator("chatgpt-assist-panel hr").count(), 1);
    assert.equal(await page.locator("chatgpt-assist-panel .code-language").textContent(), "yaml");
    assert.match(await page.locator("chatgpt-assist-panel pre code").textContent(), /<script>/);
    assert.equal(await page.getByRole("link", {name: "Source"}).getAttribute("rel"), "noopener noreferrer");
    await page.screenshot({path: "/tmp/chatgpt-assist-markdown-desktop.png", fullPage: true});
  } finally { await page.close(); }
});

test("wide tables scroll inside mobile messages in light and dark themes", async () => {
  const content = "| Sensor | Minimum | Maximum | Average | Source |\n| --- | ---: | ---: | ---: | --- |\n| Bedroom | 18 °C | 23 °C | 20.5 °C | sensor.bedroom_temperature |\n| Kitchen | 19 °C | 24 °C | 21 °C | sensor.kitchen_temperature |";
  const page = await fixture(390, [{role: "assistant", content, time: 1700000000}]);
  try {
    const scroll = page.getByRole("region", {name: "Scrollable response table"});
    assert.equal(await scroll.evaluate((el) => el.scrollWidth > el.clientWidth), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 390);
    const bounds = await scroll.boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 390);
    await scroll.focus(); await scroll.press("ArrowRight");
    await page.waitForFunction(() => document.querySelector("chatgpt-assist-panel").shadowRoot.querySelector(".table-scroll").scrollLeft > 0);
    await page.screenshot({path: "/tmp/chatgpt-assist-markdown-mobile.png", fullPage: true});
    await page.evaluate(() => {
      const panel = document.querySelector("chatgpt-assist-panel");
      for (const [key, value] of Object.entries({"--primary-background-color":"#111827", "--card-background-color":"#1f2937", "--secondary-background-color":"#283548", "--primary-text-color":"#f3f4f6", "--secondary-text-color":"#b8c1d1", "--divider-color":"#435166"})) panel.style.setProperty(key, value);
    });
    assert.equal(await page.getByRole("columnheader", {name: "Sensor"}).evaluate((el) => getComputedStyle(el).backgroundColor), "rgb(40, 53, 72)");
    await page.screenshot({path: "/tmp/chatgpt-assist-markdown-dark.png", fullPage: true});
  } finally { await page.close(); }
});

test("Markdown cannot execute HTML, embed images, or create unsafe links", async () => {
  const content = [
    "| Payload | Link |", "| --- | --- |",
    '| <img src="https://attacker.invalid/pixel" onerror="window.pwned=1"> | [unsafe](javascript:alert%281%29) |', "",
    '<script>window.pwned=2</script>', "", '<iframe src="https://attacker.invalid/iframe"></iframe>', "",
    '![tracker](https://attacker.invalid/image)', "", '[data](data:text/html,evil)', "",
    '[credentials](https://user:password@example.com/)', "", '[encoded](javascript&#58;alert%281%29)', "",
    '&lt;img src=x onerror=window.pwned=3&gt;', "", '[safe **bold**](https://example.com/?a=1&b=2)', "",
    '```html', '<img src=x onerror="window.pwned=4">', '```'
  ].join("\n");
  const page = await fixture(1200, [{role: "assistant", content, time: 1700000000}]);
  try {
    assert.equal(await page.locator("chatgpt-assist-panel .bubble img, chatgpt-assist-panel .bubble iframe, chatgpt-assist-panel .bubble script").count(), 0);
    assert.equal(await page.locator("chatgpt-assist-panel .bubble a").count(), 1);
    assert.equal(await page.getByRole("link", {name: "safe bold"}).getAttribute("href"), "https://example.com/?a=1&b=2");
    assert.equal(await page.evaluate(() => window.pwned), undefined);
    assert.equal(await page.evaluate(() => performance.getEntriesByType("resource").some((item) => item.name.includes("attacker.invalid"))), false);
    assert.match(await page.locator("chatgpt-assist-panel .bubble").textContent(), /<img src=x/);
  } finally { await page.close(); }
});

test("bundled Markdown parser matches the pinned dependency and includes its license", async () => {
  const source = (await readFile(new URL("../../node_modules/marked/lib/marked.esm.js", import.meta.url), "utf8")).replace(/^\/\/# sourceMappingURL=.*\n?/gm, "");
  assert.equal(await readFile(new URL("../../custom_components/chatgpt_assist/frontend/vendor/marked.js", import.meta.url), "utf8"), source);
  assert.equal(await readFile(new URL("../../custom_components/chatgpt_assist/frontend/vendor/marked.LICENSE", import.meta.url), "utf8"), await readFile(new URL("../../node_modules/marked/LICENSE", import.meta.url), "utf8"));
});
