export function textLength(text) {
    return Array.from(text).length;
}

export class ChatSession {
    constructor(limits) {
        this.limits = limits;
        this.messages = [];
    }

    prepare(text) {
        const content = text.trim();
        if (!content) throw new Error("Bir mesaj yazın.");
        if (textLength(content) > this.limits.max_message_chars) {
            throw new Error("Mesajınız çok uzun. Daha kısa bir mesaj yazın.");
        }
        const messages = [...this.messages, { role: "user", content }];
        if (messages.length > this.limits.max_messages ||
            messages.reduce((sum, message) => sum + textLength(message.content), 0) > this.limits.max_total_chars) {
            throw new Error("Sohbet sınırına ulaşıldı. Yeni sohbet başlatın.");
        }
        return messages.map((message) => ({ ...message }));
    }

    commit(requestMessages, answer) {
        if (typeof answer !== "string" || !answer.trim() ||
            textLength(answer.trim()) > this.limits.max_message_chars) {
            throw new Error("Geçerli bir cevap alınamadı. Tekrar deneyin.");
        }
        this.messages = [...requestMessages.map((message) => ({ ...message })),
            { role: "assistant", content: answer.trim() }];
    }

    restore(messages) {
        if (!Array.isArray(messages) || messages.length % 2 !== 0 ||
            messages.length > this.limits.max_messages) return false;
        let size = 0;
        for (const [index, message] of messages.entries()) {
            if (!message || message.role !== (index % 2 === 0 ? "user" : "assistant") ||
                typeof message.content !== "string" || !message.content.trim() ||
                textLength(message.content) > this.limits.max_message_chars) return false;
            size += textLength(message.content);
        }
        if (size > this.limits.max_total_chars + this.limits.max_message_chars) return false;
        this.messages = messages.map(({ role, content }) => ({ role, content }));
        return true;
    }
}

export async function readResponse(response) {
    let data;
    try {
        data = await response.json();
    } catch {
        throw new Error("Sunucudan geçerli bir cevap alınamadı. Tekrar deneyin.");
    }
    if (!response.ok) {
        const detail = typeof data?.detail === "string"
            ? data.detail : "İstek tamamlanamadı. Tekrar deneyin.";
        throw new Error(detail);
    }
    return data;
}

export function readSavedChat(storage) {
    try {
        if (storage.getItem("gurkan-ai:remember") !== "1") return null;
        const saved = JSON.parse(storage.getItem("gurkan-ai:chat"));
        return saved?.version === 1 ? saved : null;
    } catch {
        return null;
    }
}
