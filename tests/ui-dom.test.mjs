import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { setTimeout as pause } from "node:timers/promises";
import { JSDOM } from "jsdom";
import { ChatSession, readResponse, readSavedChat } from "../frontend/chat-state.js";

const html = fs.readFileSync(new URL("../frontend/index.html", import.meta.url), "utf8");
const appSource = fs.readFileSync(new URL("../frontend/index.js", import.meta.url), "utf8");
assert.ok(appSource.startsWith('import { ChatSession, readResponse, readSavedChat }'));
const source = appSource.slice(appSource.indexOf(";") + 1);
const limits = { max_message_chars: 8000, max_messages: 40, max_total_chars: 64000 };

async function waitFor(condition) {
    const deadline = Date.now() + 2000;
    while (!condition()) {
        if (Date.now() > deadline) throw new Error("UI state did not settle");
        await pause(2);
    }
}

function setup(t, initial = {}) {
    const dom = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only" });
    const { window } = dom;
    t.after(() => window.close());
    const state = { modelsFail: false, mode: "success", answer: "Test cevabı", timeout: 1000, ...initial };
    const requests = [];
    const pending = [];
    if (state.saved) {
        window.localStorage.setItem("gurkan-ai:remember", "1");
        window.localStorage.setItem("gurkan-ai:chat", state.saved);
    }
    Object.assign(window, { ChatSession, readResponse, readSavedChat });
    window.fetch = async (url, options = {}) => {
        if (url === "/models") {
            return new Response(JSON.stringify(state.modelsFail ? { detail: "Ollama kapalı." } : {
                models: ["qwen3.5:4b-q4_K_M", "gurkan-ai:latest"],
                limits, request_timeout_ms: state.timeout,
            }), { status: state.modelsFail ? 503 : 200 });
        }
        assert.equal(url, "/chat");
        const payload = JSON.parse(options.body);
        requests.push(payload);
        if (state.mode === "hold") {
            return new Promise((resolve, reject) => {
                pending.push(() => resolve(new Response(JSON.stringify({ answer: "Geç gelen cevap" }))));
                options.signal.addEventListener("abort", () => reject(new window.DOMException("Stopped", "AbortError")), { once: true });
            });
        }
        return new Response(JSON.stringify(state.mode === "fail"
            ? { detail: "Bağlantı hatası" } : { model: payload.model, answer: state.answer }),
        { status: state.mode === "fail" ? 503 : 200 });
    };
    window.eval(source);
    const select = (selector) => window.document.querySelector(selector);
    const send = (text) => {
        select("#messageInput").value = text;
        select("#chatForm").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
    };
    return { window, state, requests, pending, select, send };
}

test("model error disables sending, exposes retry, and recovers", async (t) => {
    const ui = setup(t, { modelsFail: true });
    await waitFor(() => !ui.select("#retryModelsButton").hidden);
    assert.equal(ui.select("#sendButton").disabled, true);
    ui.send("Blocked");
    assert.equal(ui.requests.length, 0);
    ui.state.modelsFail = false;
    ui.select("#retryModelsButton").click();
    await waitFor(() => !ui.select("#sendButton").disabled);
    assert.equal(ui.select("#modelSelect").options.length, 2);
});

test("retry reuses failed bubble and sends no duplicate history", async (t) => {
    const ui = setup(t, { mode: "fail" });
    await waitFor(() => !ui.select("#sendButton").disabled);
    ui.send("Merhaba");
    await waitFor(() => !ui.select("#retryMessageButton").hidden);
    ui.state.mode = "success";
    ui.select("#retryMessageButton").click();
    await waitFor(() => !ui.select("#sendButton").disabled);
    assert.deepEqual(ui.requests[0], ui.requests[1]);
    assert.equal(ui.window.document.querySelectorAll(".message.user").length, 1);
    assert.equal(ui.select("#retryMessageButton").hidden, true);
    ui.send("Devam");
    await waitFor(() => !ui.select("#sendButton").disabled);
    assert.equal(ui.requests[2].messages.length, 3);
    assert.deepEqual(ui.requests[2].messages.map((message) => message.role), ["user", "assistant", "user"]);
});

test("failed message can be edited without leaving old content in context", async (t) => {
    const ui = setup(t, { mode: "fail" });
    await waitFor(() => !ui.select("#sendButton").disabled);
    ui.send("Eski");
    await waitFor(() => !ui.select("#retryMessageButton").hidden);
    ui.state.mode = "success";
    ui.send("Düzeltilmiş");
    await waitFor(() => !ui.select("#sendButton").disabled);
    assert.deepEqual(ui.requests[1].messages, [{ role: "user", content: "Düzeltilmiş" }]);
    assert.equal(ui.select(".message.user").textContent, "Düzeltilmiş");
});

test("stop aborts pending request and permits retry", async (t) => {
    const ui = setup(t, { mode: "hold" });
    await waitFor(() => !ui.select("#sendButton").disabled);
    ui.send("Durdur");
    await waitFor(() => ui.requests.length === 1);
    ui.select("#stopButton").click();
    await waitFor(() => !ui.select("#retryMessageButton").hidden);
    assert.match(ui.select(".message.error").textContent, /durduruldu/);
    assert.equal(ui.select("#sendButton").disabled, false);
    ui.pending[0]();
    await pause(5);
    assert.equal(ui.window.document.body.textContent.includes("Geç gelen cevap"), false);
});

test("new chat prevents a late response from entering the next conversation", async (t) => {
    const ui = setup(t, { mode: "hold" });
    await waitFor(() => !ui.select("#sendButton").disabled);
    ui.send("Eski sohbet");
    await waitFor(() => ui.requests.length === 1);
    ui.select("#newChatButton").click();
    ui.pending[0]();
    await pause(5);
    assert.equal(ui.window.document.querySelectorAll(".message").length, 1);
    assert.equal(ui.select("#stopButton").hidden, true);
    ui.state.mode = "success";
    ui.send("Yeni sohbet");
    await waitFor(() => !ui.select("#sendButton").disabled);
    assert.equal(ui.requests[1].messages.length, 1);
});

test("frontend deadline restores controls after a hanging request", async (t) => {
    const ui = setup(t, { mode: "hold", timeout: 15 });
    await waitFor(() => !ui.select("#sendButton").disabled);
    ui.send("Soru");
    await waitFor(() => !ui.select("#retryMessageButton").hidden);
    assert.match(ui.select(".message.error").textContent, /süresi doldu/);
    assert.equal(ui.select("#sendButton").disabled, false);
});

test("history is stored only with opt-in, restored and removable", async (t) => {
    const ui = setup(t);
    await waitFor(() => !ui.select("#sendButton").disabled);
    ui.send("Kaydet");
    await waitFor(() => !ui.select("#sendButton").disabled);
    assert.equal(ui.window.localStorage.getItem("gurkan-ai:chat"), null);
    ui.select("#rememberChat").click();
    const saved = ui.window.localStorage.getItem("gurkan-ai:chat");
    assert.equal(JSON.parse(saved).messages.length, 2);
    const restored = setup(t, { saved });
    await waitFor(() => !restored.select("#sendButton").disabled);
    assert.equal(restored.select("#rememberChat").checked, true);
    assert.equal(restored.select(".message.user").textContent, "Kaydet");
    restored.select("#rememberChat").click();
    assert.equal(restored.window.localStorage.getItem("gurkan-ai:chat"), null);
});

test("model change resets context, and messages render as text", async (t) => {
    const ui = setup(t, { answer: "<script>alert(1)</script>" });
    await waitFor(() => !ui.select("#sendButton").disabled);
    ui.send("<img src=x onerror=alert(1)>");
    await waitFor(() => !ui.select("#sendButton").disabled);
    assert.equal(ui.select("#messages img"), null);
    assert.equal(ui.select("#messages script"), null);
    ui.select("#modelSelect").value = "gurkan-ai:latest";
    ui.select("#modelSelect").dispatchEvent(new ui.window.Event("change"));
    assert.equal(ui.select(".message.user"), null);
    ui.state.answer = "Yeni cevap";
    ui.send("Yeni model");
    await waitFor(() => !ui.select("#sendButton").disabled);
    assert.equal(ui.requests[1].model, "gurkan-ai:latest");
    assert.equal(ui.requests[1].messages.length, 1);
});
