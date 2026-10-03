import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const baseURL = process.env.TEST_BASE_URL || "http://127.0.0.1:8000";
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1100, height: 850 } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
let modelsFail = true;
let chatMode = "fail";
let gate;
const requests = [];
const models = {
    models: ["qwen3.5:4b-q4_K_M", "gurkan-ai:latest"],
    limits: { max_message_chars: 8000, max_messages: 40, max_total_chars: 64000 },
    request_timeout_ms: 5000,
};

await page.route("**/models", (route) => route.fulfill({
    status: modelsFail ? 503 : 200,
    json: modelsFail ? { detail: "Ollama kapalı. Yeniden deneyin." } : models,
}));
await page.route("**/chat", async (route) => {
    const payload = route.request().postDataJSON();
    requests.push(payload);
    const currentMode = chatMode;
    if (currentMode === "hold") await gate.promise;
    try {
        await route.fulfill(currentMode === "fail"
            ? { status: 503, json: { detail: "Bağlantı kurulamadı." } }
            : { status: 200, json: { model: payload.model, answer: "Kontrollü test cevabı." } });
    } catch (error) {
        if (!/closed|cancel|intercept|abort|handled/i.test(error.message)) throw error;
    }
});

function holdNext() {
    chatMode = "hold";
    let release;
    const promise = new Promise((resolve) => { release = resolve; });
    gate = { promise, release };
}
async function send(text) {
    await page.locator("#messageInput").fill(text);
    const outgoing = page.waitForRequest((request) => request.url().endsWith("/chat"));
    await page.locator("#sendButton").click();
    await outgoing;
}

try {
    await page.goto(baseURL, { waitUntil: "domcontentloaded" });
    await page.locator("#retryModelsButton").waitFor({ state: "visible" });
    assert.equal(await page.locator("#sendButton").isDisabled(), true);
    assert.equal(await page.locator("#messageInput").isDisabled(), true);
    console.log("PASS: model load failure blocks sending");

    modelsFail = false;
    await page.locator("#retryModelsButton").click();
    await page.waitForFunction(() => !document.querySelector("#sendButton").disabled);
    assert.equal(await page.locator("#modelSelect option").count(), 2);
    console.log("PASS: model loading can be retried");

    await send("İlk soru");
    await page.locator("#retryMessageButton").waitFor({ state: "visible" });
    chatMode = "success";
    await page.locator("#retryMessageButton").click();
    await page.getByText("Kontrollü test cevabı.", { exact: true }).waitFor();
    assert.equal(requests.length, 2);
    assert.deepEqual(requests[0].messages, requests[1].messages);
    assert.equal(await page.locator(".message.user").count(), 1);
    console.log("PASS: failed turn retries without duplicate history or bubbles");

    await send("<img src=x onerror=alert(1)>");
    await page.waitForFunction(() => !document.querySelector("#sendButton").disabled);
    assert.equal(requests.at(-1).messages.length, 3);
    assert.equal(await page.locator("#messages img").count(), 0);
    console.log("PASS: next turn has only completed history and renders text safely");

    await page.locator("#rememberChat").check();
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => !document.querySelector("#sendButton").disabled);
    assert.equal(await page.locator(".message.user").count(), 2);
    assert.equal(await page.locator("#rememberChat").isChecked(), true);
    await page.locator("#rememberChat").uncheck();
    assert.equal(await page.evaluate(() => localStorage.getItem("gurkan-ai:chat")), null);
    console.log("PASS: opt-in history survives reload and can be removed");

    await page.locator("#newChatButton").click();
    holdNext();
    await send("Durdurulacak soru");
    await page.locator("#stopButton").click();
    await page.locator("#retryMessageButton").waitFor({ state: "visible" });
    assert.match(await page.locator(".message.error").innerText(), /durduruldu/);
    gate.release();
    assert.equal(await page.locator("#sendButton").isEnabled(), true);
    console.log("PASS: stop restores controls and allows retry");

    holdNext();
    await send("Eski sohbetin sorusu");
    await page.locator("#newChatButton").click();
    gate.release();
    await page.waitForTimeout(100);
    assert.equal(await page.locator(".message").count(), 1);
    assert.equal(await page.locator(".message.user").count(), 0);
    console.log("PASS: new chat isolates late responses");

    chatMode = "success";
    await send("Yeni soru");
    await page.waitForFunction(() => !document.querySelector("#sendButton").disabled);
    assert.equal(requests.at(-1).messages.length, 1);
    await page.locator("#modelSelect").selectOption("gurkan-ai:latest");
    assert.equal(await page.locator(".message.user").count(), 0);
    console.log("PASS: model change starts clean context");

    await page.setViewportSize({ width: 360, height: 780 });
    const dimensions = await page.evaluate(() => ({
        viewport: innerWidth,
        content: document.documentElement.scrollWidth,
        input: document.querySelector("#messageInput").getBoundingClientRect().toJSON(),
    }));
    assert.ok(dimensions.content <= dimensions.viewport);
    assert.ok(dimensions.input.left >= 0 && dimensions.input.right <= dimensions.viewport);
    console.log("PASS: 360px mobile layout has no horizontal overflow");

    if (process.env.SCREENSHOT_DIR) {
        await fs.mkdir(process.env.SCREENSHOT_DIR, { recursive: true });
        await page.screenshot({ path: path.join(process.env.SCREENSHOT_DIR, "mobile.png"), fullPage: true });
        await page.setViewportSize({ width: 1100, height: 850 });
        await page.screenshot({ path: path.join(process.env.SCREENSHOT_DIR, "desktop.png"), fullPage: true });
    }
    assert.deepEqual(errors, []);
    console.log("PASS: no uncaught browser errors");
} finally {
    gate?.release();
    await browser.close();
}
