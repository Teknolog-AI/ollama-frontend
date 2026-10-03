import { ChatSession, readResponse, readSavedChat } from "./chat-state.js";

const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const messagesElement = document.querySelector("#messages");
const modelSelect = document.querySelector("#modelSelect");
const sendButton = document.querySelector("#sendButton");
const stopButton = document.querySelector("#stopButton");
const newChatButton = document.querySelector("#newChatButton");
const retryModelsButton = document.querySelector("#retryModelsButton");
const retryMessageButton = document.querySelector("#retryMessageButton");
const statusElement = document.querySelector("#status");
const remember = document.querySelector("#rememberChat");

let session = null;
let ready = false;
let activeRequest = null;
let modelRequest = null;
let failedTurn = null;
let generation = 0;
let requestTimeout = 185000;

function status(text, error = false) {
    statusElement.textContent = text;
    statusElement.classList.toggle("error", error);
}

function controls() {
    const busy = Boolean(activeRequest);
    sendButton.disabled = !ready || busy;
    input.disabled = !ready || busy;
    modelSelect.disabled = !ready || busy;
    stopButton.hidden = !busy;
    retryMessageButton.hidden = !failedTurn || busy;
    retryMessageButton.disabled = !ready || busy;
    retryModelsButton.disabled = busy || Boolean(modelRequest);
    messagesElement.setAttribute("aria-busy", String(busy));
}

function addMessage(content, role, extraClass = "") {
    const element = document.createElement("div");
    element.className = "message " + role + " " + extraClass;
    element.textContent = content;
    messagesElement.appendChild(element);
    messagesElement.scrollTop = messagesElement.scrollHeight;
    return element;
}

function storage() {
    try { return window.localStorage; } catch { return null; }
}

function persist() {
    const store = storage();
    if (!store) {
        if (remember.checked) status("Bu tarayıcı sohbet kaydına izin vermiyor.", true);
        return;
    }
    try {
        if (remember.checked && session) {
            store.setItem("gurkan-ai:remember", "1");
            store.setItem("gurkan-ai:chat", JSON.stringify({
                version: 1, model: modelSelect.value, messages: session.messages,
            }));
        } else {
            store.removeItem("gurkan-ai:remember");
            store.removeItem("gurkan-ai:chat");
        }
    } catch {
        status("Sohbet bu cihaza kaydedilemedi. Sohbete devam edebilirsiniz.", true);
    }
}

function resetChat() {
    generation += 1;
    activeRequest?.controller.abort();
    activeRequest = null;
    failedTurn = null;
    if (session) session = new ChatSession(session.limits);
    messagesElement.replaceChildren();
    addMessage("Hangi konuda eğitim almak istiyorsunuz?", "assistant");
    input.value = "";
    status(ready ? "Yeni sohbet hazır." : "Önce kullanılabilir modelleri yükleyin.");
    persist();
    controls();
    if (ready) input.focus();
}

async function loadModels() {
    modelRequest?.abort();
    const controller = new AbortController();
    modelRequest = controller;
    ready = false;
    status("Modeller kontrol ediliyor…");
    retryModelsButton.hidden = true;
    controls();
    const timer = setTimeout(() => controller.abort(), 65000);
    try {
        const data = await readResponse(await fetch("/models", { signal: controller.signal }));
        if (!Array.isArray(data.models) || data.models.some((name) => typeof name !== "string" || !name) ||
            !data.limits || !["max_message_chars", "max_messages", "max_total_chars"].every(
                (key) => Number.isInteger(data.limits[key]) && data.limits[key] > 0) ||
            !Number.isFinite(data.request_timeout_ms) || data.request_timeout_ms <= 0) {
            throw new Error("Model listesi alınamadı. Tekrar deneyin.");
        }
        if (!data.models.length) {
            throw new Error("İzin verilen modellerden hiçbiri Ollama'da kurulu değil. Bir model kurup listeyi yenileyin.");
        }
        if (modelRequest !== controller) return;
        const previousModel = modelSelect.value;
        const previousSession = session;
        modelSelect.replaceChildren();
        for (const model of data.models) {
            const option = document.createElement("option");
            option.value = model;
            option.textContent = model;
            modelSelect.appendChild(option);
        }
        session = new ChatSession(data.limits);
        requestTimeout = data.request_timeout_ms;
        input.maxLength = data.limits.max_message_chars;
        const saved = readSavedChat(storage());
        let restored = false;
        if (previousSession && data.models.includes(previousModel)) {
            modelSelect.value = previousModel;
            session.restore(previousSession.messages);
            restored = true;
        } else if (saved && data.models.includes(saved.model) && session.restore(saved.messages)) {
            modelSelect.value = saved.model;
            remember.checked = true;
        }
        if (!restored) {
            failedTurn = null;
            messagesElement.replaceChildren();
            if (session.messages.length) {
                for (const message of session.messages) addMessage(message.content, message.role);
            } else {
                addMessage("Hangi konuda eğitim almak istiyorsunuz?", "assistant");
            }
        }
        ready = true;
        status("Hazır. Mesajınızı yazabilirsiniz.");
    } catch (error) {
        if (modelRequest !== controller) return;
        status(controller.signal.aborted ? "Model listesini alma süresi doldu. Tekrar deneyin." : error.message, true);
        retryModelsButton.hidden = false;
    } finally {
        clearTimeout(timer);
        if (modelRequest === controller) {
            modelRequest = null;
            controls();
        }
    }
}

async function sendMessage(text) {
    if (!ready || activeRequest || !session) return;
    let requestMessages;
    try {
        requestMessages = session.prepare(text);
    } catch (error) {
        status(error.message, true);
        return;
    }
    const content = requestMessages.at(-1).content;
    let userElement;
    if (failedTurn) {
        userElement = failedTurn.userElement;
        userElement.textContent = content;
        userElement.classList.remove("failed");
        failedTurn.errorElement.remove();
    } else {
        userElement = addMessage(content, "user");
    }
    failedTurn = null;
    const loading = addMessage("Yanıt hazırlanıyor…", "assistant", "loading");
    const controller = new AbortController();
    const token = { controller, generation };
    activeRequest = token;
    input.value = "";
    status("Yanıt hazırlanıyor…");
    controls();
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, requestTimeout);
    try {
        const data = await readResponse(await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model: modelSelect.value, messages: requestMessages }),
            signal: controller.signal,
        }));
        if (token.generation !== generation) return;
        if (controller.signal.aborted) throw new DOMException("İstek durduruldu.", "AbortError");
        session.commit(requestMessages, data?.answer);
        loading.remove();
        addMessage(data.answer.trim(), "assistant");
        status("Hazır.");
        persist();
    } catch (error) {
        if (token.generation !== generation) return;
        const detail = controller.signal.aborted
            ? (timedOut ? "Yanıt süresi doldu. Tekrar deneyebilirsiniz." : "İstek durduruldu. Tekrar deneyebilirsiniz.")
            : (error instanceof TypeError ? "Sunucuya ulaşılamadı. Bağlantıyı kontrol edip tekrar deneyin." : error.message);
        loading.textContent = detail;
        loading.classList.remove("loading");
        loading.classList.add("error");
        userElement.classList.add("failed");
        failedTurn = { content, userElement, errorElement: loading };
        input.value = content;
        status("Mesaj tamamlanmadı. Düzenleyip gönderebilir veya yeniden deneyebilirsiniz.", true);
    } finally {
        clearTimeout(timer);
        if (activeRequest === token) {
            activeRequest = null;
            controls();
            input.focus();
        }
    }
}

form.addEventListener("submit", (event) => {
    event.preventDefault();
    void sendMessage(input.value);
});
retryMessageButton.addEventListener("click", () => {
    if (failedTurn) void sendMessage(failedTurn.content);
});
retryModelsButton.addEventListener("click", () => void loadModels());
stopButton.addEventListener("click", () => activeRequest?.controller.abort());
newChatButton.addEventListener("click", resetChat);
modelSelect.addEventListener("change", resetChat);
remember.addEventListener("change", persist);
input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        if (!sendButton.disabled) form.requestSubmit();
    }
});
controls();
void loadModels();
