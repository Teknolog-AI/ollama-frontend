const API_URL = "http://127.0.0.1:8000";

const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const messagesElement = document.querySelector("#messages");
const modelSelect = document.querySelector("#modelSelect");
const button = form.querySelector("button");

const chatHistory = [];

function addMessage(content, role, extraClass = "") {
    const element = document.createElement("div");

    element.className = `message ${role} ${extraClass}`;
    element.textContent = content;

    messagesElement.appendChild(element);
    messagesElement.scrollTop = messagesElement.scrollHeight;

    return element;
}

async function loadModels() {
    const response = await fetch(`${API_URL}/models`);
    const data = await response.json();

    data.models.forEach((model) => {
        const option = document.createElement("option");
        option.value = model;
        option.textContent = model;
        modelSelect.appendChild(option);
    });
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const userMessage = input.value.trim();

    if (!userMessage) {
        return;
    }

    addMessage(userMessage, "user");
    chatHistory.push({
        role: "user",
        content: userMessage,
    });

    input.value = "";
    button.disabled = true;

    const loadingMessage = addMessage(
        "Yanıt hazırlanıyor...",
        "assistant",
        "loading"
    );

    try {
        const response = await fetch(`${API_URL}/chat`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                model: modelSelect.value,
                messages: chatHistory,
            }),
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail);
        }

        loadingMessage.remove();
        addMessage(data.answer, "assistant");

        chatHistory.push({
            role: "assistant",
            content: data.answer,
        });
    } catch (error) {
        loadingMessage.textContent =
            error.message || "Bağlantı hatası oluştu.";
    } finally {
        button.disabled = false;
        input.focus();
    }
});

loadModels();