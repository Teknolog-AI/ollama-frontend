import test from "node:test";
import assert from "node:assert/strict";
import { ChatSession, readResponse, readSavedChat } from "../frontend/chat-state.js";

const limits = { max_message_chars: 20, max_messages: 5, max_total_chars: 50 };

test("failed or cancelled attempts do not commit user messages", () => {
    const chat = new ChatSession(limits);
    const first = chat.prepare(" Merhaba ");
    const retry = chat.prepare("Merhaba");
    assert.deepEqual(first, retry);
    assert.deepEqual(chat.messages, []);
    chat.commit(retry, "Selam");
    assert.equal(chat.messages.length, 2);
    assert.equal(chat.prepare("Devam").length, 3);
});

test("invalid answers never contaminate committed history", () => {
    const chat = new ChatSession(limits);
    for (const answer of ["", "   ", null, "a".repeat(21)]) {
        assert.throws(() => chat.commit(chat.prepare("Soru"), answer));
        assert.deepEqual(chat.messages, []);
    }
});

test("blank, long and overflowing conversations stop before sending", () => {
    const chat = new ChatSession(limits);
    assert.throws(() => chat.prepare("  "));
    assert.throws(() => chat.prepare("x".repeat(21)));
    chat.commit(chat.prepare("x".repeat(20)), "y".repeat(20));
    assert.throws(() => chat.prepare("z".repeat(20)));
});

test("message count is bounded", () => {
    const chat = new ChatSession(limits);
    for (let i = 0; i < 3; i++) chat.commit(chat.prepare("x"), "y");
    assert.throws(() => chat.prepare("x"));
});

test("Unicode code points count like Python validation", () => {
    const chat = new ChatSession({ ...limits, max_message_chars: 2 });
    assert.equal(chat.prepare("😀😀")[0].content, "😀😀");
    assert.throws(() => chat.prepare("😀😀😀"));
});

test("saved history validates role ordering, shape and size", () => {
    const chat = new ChatSession(limits);
    const valid = [{ role: "user", content: "Soru" }, { role: "assistant", content: "Cevap" }];
    assert.equal(chat.restore(valid), true);
    for (const invalid of [null, [null, null], [valid[1], valid[0]], [valid[0]], [
        { role: "user", content: "<script>" }, { role: "system", content: "X" },
    ]]) assert.equal(chat.restore(invalid), false);
    assert.deepEqual(chat.messages, valid);
});

test("restored and prepared messages are copied", () => {
    const chat = new ChatSession(limits);
    const source = [{ role: "user", content: "Soru" }, { role: "assistant", content: "Cevap" }];
    chat.restore(source);
    source[0].content = "Changed";
    const request = chat.prepare("Yeni");
    request[0].content = "Changed again";
    assert.equal(chat.messages[0].content, "Soru");
});

test("HTTP errors and malformed JSON show useful text", async () => {
    await assert.rejects(readResponse(new Response(JSON.stringify({ detail: "Model bulunamadı." }), { status: 404 })), /Model bulunamadı/);
    await assert.rejects(readResponse(new Response("bad JSON")), /geçerli bir cevap/);
    await assert.rejects(readResponse(new Response(JSON.stringify({ detail: [{ msg: "bad" }] }), { status: 422 })), /İstek tamamlanamadı/);
    assert.deepEqual(await readResponse(new Response('{"answer":"ok"}')), { answer: "ok" });
});

test("storage opt-in and invalid data are handled without exceptions", () => {
    assert.equal(readSavedChat(null), null);
    assert.equal(readSavedChat({ getItem() { throw new Error("blocked"); } }), null);
    const values = new Map([["gurkan-ai:remember", "1"], ["gurkan-ai:chat", "{bad"]]);
    const storage = { getItem: (key) => values.get(key) };
    assert.equal(readSavedChat(storage), null);
    values.set("gurkan-ai:chat", JSON.stringify({ version: 1, model: "demo", messages: [] }));
    assert.equal(readSavedChat(storage).model, "demo");
    values.set("gurkan-ai:remember", "0");
    assert.equal(readSavedChat(storage), null);
});
