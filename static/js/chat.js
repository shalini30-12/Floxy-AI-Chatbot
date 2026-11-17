// ---------------------------------------------------------------------
// chat.js — Floxy frontend logic
// Handles: sending text messages, voice input/output (Web Speech API),
// file uploads, and live autocomplete suggestions.
// ---------------------------------------------------------------------

const chatScroll   = document.getElementById("chat-scroll");
const msgInput     = document.getElementById("msg-input");
const sendBtn      = document.getElementById("send-btn");
const micBtn       = document.getElementById("mic-btn");
const fileInput    = document.getElementById("file-input");
const filePreview  = document.getElementById("file-preview");
const suggestionsEl= document.getElementById("suggestions");
const composerHint = document.getElementById("composer-hint");
const modePills    = document.querySelectorAll(".pill[data-mode]");
const activeDocBadge = document.getElementById("active-doc-badge");
const activeDocName  = document.getElementById("active-doc-name");
const clearDocBtn    = document.getElementById("clear-doc-btn");

function setActiveDocument(name) {
    if (name) {
        activeDocName.textContent = `📄 ${name}`;
        activeDocBadge.classList.remove("hidden");
    } else {
        activeDocBadge.classList.add("hidden");
    }
}

clearDocBtn.addEventListener("click", async () => {
    await fetch("/api/clear-document", { method: "POST" });
    setActiveDocument(null);
});

let currentMode = "text";      // "text" | "voice"
let pendingFile = null;
let pendingFiles = [];
let currentViewDate = "";
let bookmarkedIds = new Set();
let suggestTimer = null;

// ---------------- Helpers ----------------
function scrollToBottom() {
    chatScroll.scrollTop = chatScroll.scrollHeight;
}


function renderMusicLinks(col, links) {
    const box = document.createElement("div");
    box.className = "music-options";
    links.forEach((l) => {
        const a = document.createElement("a");
        a.className = "music-btn";
        a.href = l.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = `${l.icon} ${l.name}`;
        box.appendChild(a);
    });
    const meta = col.querySelector(".bubble-meta-row");
    if (meta) col.insertBefore(box, meta);
    else col.appendChild(box);
}


function formatRelativeTime(dateInput) {
    const then = typeof dateInput === "string" ? new Date(dateInput.replace(" ", "T")) : dateInput;
    const diffMin = Math.floor((new Date() - then) / 60000);
    if (diffMin < 1) return "just now";
    if (diffMin < 60) return `${diffMin} min ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr} hour${diffHr > 1 ? "s" : ""} ago`;
    const diffDay = Math.floor(diffHr / 24);
    return `${diffDay} day${diffDay > 1 ? "s" : ""} ago`;
}

function appendMessage(role, text, timestamp, musicLinks, fileInfo) {
    const row = document.createElement("div");
    row.className = `msg msg-${role}`;

    const col = document.createElement("div");
    col.className = "bubble-col";

    const wrap = document.createElement("div");
    wrap.className = "bubble-wrap";

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    wrap.appendChild(bubble);

    const metaRow = document.createElement("div");
    metaRow.className = "bubble-meta-row";

    const actions = document.createElement("div");
    actions.className = "bubble-actions";

    const copyBtn = document.createElement("button");
    copyBtn.className = "bubble-action-btn";
    copyBtn.title = "Copy";
    copyBtn.textContent = "📋";
    copyBtn.addEventListener("click", () => {
        navigator.clipboard.writeText(bubble.textContent);
        copyBtn.textContent = "✅";
        setTimeout(() => (copyBtn.textContent = "📋"), 1200);
    });
    actions.appendChild(copyBtn);

    if (role === "user") {
        const editBtn = document.createElement("button");
        editBtn.className = "bubble-action-btn";
        editBtn.title = "Edit";
        editBtn.textContent = "✏️";
        editBtn.addEventListener("click", () => {
            msgInput.value = bubble.textContent;
            msgInput.style.height = "auto";
            msgInput.style.height = msgInput.scrollHeight + "px";
            msgInput.focus();
        });
        actions.appendChild(editBtn);
    }

    const timeEl = document.createElement("div");
    timeEl.className = "bubble-time";
    timeEl.textContent = formatRelativeTime(timestamp || new Date());

    metaRow.appendChild(actions);
    metaRow.appendChild(timeEl);
    col.appendChild(wrap);
    col.appendChild(metaRow);
    if (musicLinks && musicLinks.length) renderMusicLinks(col, musicLinks);
    if (fileInfo) renderSavedFile(col, fileInfo);
    row.appendChild(col);
    chatScroll.appendChild(row);
    scrollToBottom();
    return bubble;
}

function speak(text) {
    if (currentMode !== "voice" || !("speechSynthesis" in window)) return;
    const utter = new SpeechSynthesisUtterance(text);
    utter.rate = 1.0;
    window.speechSynthesis.speak(utter);
}

// ---------------- Mode switch ----------------
modePills.forEach((pill) => {
    pill.addEventListener("click", () => {
        modePills.forEach((p) => p.classList.remove("active"));
        pill.classList.add("active");
        currentMode = pill.dataset.mode;
        composerHint.textContent = currentMode === "voice" ? "Voice mode — tap the mic to speak" : "Text mode";
    });
});

// ---------------- Sending a text message ----------------

const isImageFile = (f) => /\.(png|jpe?g|webp)$/i.test(f.name);

function wantsPdfConversion(text) {
    const t = (text || "").toLowerCase();
    return /\bpdf\b/.test(t) && /(convert|bana|make|create|merge|combine|jod|save|export|generate|badal)/.test(t);
}

function clearPendingFiles() {
    pendingFiles = [];
    pendingFile = null;
    filePreview.textContent = "";
    fileInput.value = "";
}

function renderPdfDownload(col, blob, fileName) {
    const url = URL.createObjectURL(blob);
    const box = document.createElement("div");
    box.className = "pdf-result";

    const dl = document.createElement("a");
    dl.className = "pdf-result-btn";
    dl.href = url;
    dl.download = fileName;
    dl.textContent = "⬇️ Download PDF";

    const view = document.createElement("a");
    view.className = "pdf-result-btn";
    view.href = url;
    view.target = "_blank";
    view.rel = "noopener";
    view.textContent = "👁️ Open";

    box.appendChild(dl);
    box.appendChild(view);
    const meta = col.querySelector(".bubble-meta-row");
    if (meta) col.insertBefore(box, meta);
    else col.appendChild(box);
}

function wantsImageConversion(text) {
    const t = (text || "").toLowerCase();
    return /(image|img|jpg|jpeg|png|photo|picture)/.test(t) &&
           /(convert|bana|make|create|badal|export|save|extract|nikal|change)/.test(t);
}

function renderDownloadButtons(col, blob, fileName, canOpen) {
    const url = URL.createObjectURL(blob);
    const box = document.createElement("div");
    box.className = "pdf-result";

    const dl = document.createElement("a");
    dl.className = "pdf-result-btn";
    dl.href = url;
    dl.download = fileName;
    dl.textContent = "⬇️ Download";
    box.appendChild(dl);

    if (canOpen) {
        const view = document.createElement("a");
        view.className = "pdf-result-btn";
        view.href = url;
        view.target = "_blank";
        view.rel = "noopener";
        view.textContent = "👁️ Open";
        box.appendChild(view);
    }

    const meta = col.querySelector(".bubble-meta-row");
    if (meta) col.insertBefore(box, meta);
    else col.appendChild(box);
}

function renderSavedFile(col, f) {
    const holder = document.createElement("div");
    holder.className = "saved-file";

    if (f.is_image) {
        const a = document.createElement("a");
        a.href = f.url;
        a.target = "_blank";
        a.rel = "noopener";
        const img = document.createElement("img");
        img.className = "poster-preview";
        img.src = f.url;
        img.alt = f.name;
        img.loading = "lazy";
        img.addEventListener("load", scrollToBottom);
        a.appendChild(img);
        holder.appendChild(a);
    }

    const box = document.createElement("div");
    box.className = "pdf-result";

    const dl = document.createElement("a");
    dl.className = "pdf-result-btn";
    dl.href = `${f.url}?dl=1`;
    dl.textContent = "⬇️ Download";
    box.appendChild(dl);

    if (f.can_open) {
        const view = document.createElement("a");
        view.className = "pdf-result-btn";
        view.href = f.url;
        view.target = "_blank";
        view.rel = "noopener";
        view.textContent = "👁️ Open";
        box.appendChild(view);
    }

    holder.appendChild(box);
    const meta = col.querySelector(".bubble-meta-row");
    if (meta) col.insertBefore(holder, meta);
    else col.appendChild(holder);
}

async function sendMessage() {
    if (currentViewDate !== "") {
        await loadHistoryForDate("");
    }
    const text = msgInput.value.trim();
    if (!text && !pendingFile) return;

    suggestionsEl.innerHTML = "";
    // ---- "poster banao" typed in chat -> open the poster form ----
    if (pendingFiles.length === 0 && wantsPoster(text)) {
        appendMessage("user", text);
        appendMessage("bot", "Poster ke liye neeche wala form bhar do, main bana deta hoon. 🎨");
        msgInput.value = "";
        msgInput.style.height = "auto";
        openPosterModal();
        return;
    }

    // ---- Images -> one PDF ----
    if (pendingFiles.length > 0 && pendingFiles.every(isImageFile) && wantsPdfConversion(text)) {
        const files = pendingFiles;
        appendMessage("user", `🖼️ ${files.length} image${files.length > 1 ? "s" : ""} — ${text}`);
        msgInput.value = "";
        clearPendingFiles();
        const botMsg = appendBotPlaceholder();

        try {
            const formData = new FormData();
            files.forEach((f) => formData.append("images", f));
            const res = await fetch("/api/images-to-pdf", { method: "POST", body: formData });
            const ctype = res.headers.get("Content-Type") || "";

            if (res.status === 413) {
                botMsg.bubble.textContent = "Images ka total size bahut bada hai (limit 50 MB).";
            } else if (ctype.includes("application/pdf")) {
                const blob = await res.blob();
                botMsg.bubble.textContent = `✅ ${files.length} image${files.length > 1 ? "s" : ""} ka PDF ready hai.`;
                renderPdfDownload(botMsg.col, blob, "floxy_images.pdf");
            } else {
                const data = await res.json();
                botMsg.bubble.textContent = data.error || "PDF nahi ban payi.";
            }
        } catch (e) {
            botMsg.bubble.textContent = "Network error — please try again.";
        }
        botMsg.timeEl.textContent = formatRelativeTime(new Date());
        botMsg.copyBtn.style.display = "";
        return;}
    // ---- PDF -> images ----
    if (pendingFiles.length === 1 && /\.pdf$/i.test(pendingFiles[0].name) && wantsImageConversion(text)) {
        const pdfFile = pendingFiles[0];
        const fmt = /\b(jpg|jpeg)\b/i.test(text) ? "jpg" : "png";
        appendMessage("user", `📄 ${pdfFile.name} — ${text}`);
        msgInput.value = "";
        clearPendingFiles();
        const botMsg = appendBotPlaceholder();

        try {
            const formData = new FormData();
            formData.append("pdf", pdfFile);
            formData.append("format", fmt);
            const res = await fetch("/api/pdf-to-images", { method: "POST", body: formData });
            const ctype = res.headers.get("Content-Type") || "";

            if (res.status === 413) {
                botMsg.bubble.textContent = "PDF ka size bahut bada hai (limit 50 MB).";
            } else if (res.ok && !ctype.includes("application/json")) {
                const blob = await res.blob();
                const pages = res.headers.get("X-Page-Count") || "1";
                const base = pdfFile.name.replace(/\.pdf$/i, "");
                const isZip = ctype.includes("zip");
                const fileName = isZip ? `${base}_images.zip` : `${base}.${fmt}`;
                botMsg.bubble.textContent = isZip
                    ? `✅ ${pages} pages ki images ready hain. Sab ek ZIP mein hain, har page ki alag image.`
                    : "✅ PDF ki image ready hai.";
                renderDownloadButtons(botMsg.col, blob, fileName, !isZip);
            } else {
                const data = await res.json();
                botMsg.bubble.textContent = data.error || "Image nahi ban payi.";
            }
        } catch (e) {
            botMsg.bubble.textContent = "Network error — please try again.";
        }
        botMsg.timeEl.textContent = formatRelativeTime(new Date());
        botMsg.copyBtn.style.display = "";
        return;
    }
    // Many files but no "convert to pdf" request
    if (pendingFiles.length > 1) {
        appendMessage("user", `📎 ${pendingFiles.length} files${text ? " — " + text : ""}`);
        appendMessage("bot", "Kai files ek saath bhejni hain to sirf images select karo aur message mein 'convert to pdf' likho. Kisi file ko analyse karna ho to ek hi file select karo.");
        msgInput.value = "";
        clearPendingFiles();
        return;
    }

    if (pendingFile) {
        appendMessage("user", `📎 ${pendingFile.name}${text ? " — " + text : ""}`);
        const formData = new FormData();
        formData.append("file", pendingFile);
        formData.append("prompt", text);

        msgInput.value = "";
        const botMsg = appendBotPlaceholder();
        clearPendingFiles();

        try {
            const res = await fetch("/api/upload", { method: "POST", body: formData });
            const data = await res.json();
            botMsg.bubble.textContent = data.reply || data.error || "Something went wrong.";
            botMsg.timeEl.textContent = formatRelativeTime(new Date());
            botMsg.copyBtn.style.display = "";
            speak(botMsg.bubble.textContent);
            setActiveDocument(data.active_document || null);
        } catch (e) {
            botMsg.bubble.textContent = "Network error — please try again.";
            botMsg.timeEl.textContent = formatRelativeTime(new Date());
            botMsg.copyBtn.style.display = "";
        }
        return;
    }
    appendMessage("user", text);
    msgInput.value = "";
    msgInput.style.height = "auto";

    const botMsg = appendBotPlaceholder();

    try {
        const res = await fetch("/api/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text, mode: currentMode }),
        });
        const data = await res.json();
        botMsg.bubble.textContent = data.reply || data.error || "Something went wrong.";
        botMsg.timeEl.textContent = formatRelativeTime(new Date());
        botMsg.copyBtn.style.display = "";
        if (data.music_links && data.music_links.length) renderMusicLinks(botMsg.col, data.music_links);
        speak(botMsg.bubble.textContent);
    } catch (e) {
        botMsg.bubble.textContent = "Network error — please try again.";
        botMsg.timeEl.textContent = formatRelativeTime(new Date());
        botMsg.copyBtn.style.display = "";
    }
}

sendBtn.addEventListener("click", sendMessage);
msgInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});
msgInput.addEventListener("input", () => {
    msgInput.style.height = "auto";
    msgInput.style.height = msgInput.scrollHeight + "px";
    //debounceSuggestions();
});

// ---------------- File upload ----------------
fileInput.addEventListener("change", () => {
    pendingFiles = Array.from(fileInput.files);
    pendingFile = pendingFiles[0] || null;
    if (pendingFiles.length === 1) {
        filePreview.textContent = `Ready: ${pendingFiles[0].name}`;
    } else if (pendingFiles.length > 1) {
        filePreview.textContent = `Ready: ${pendingFiles.length} files, 'convert to pdf' likho`;
    }


    
});

// ---------------- Voice input (Speech-to-Text) ----------------
const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;
let listening = false;

if (SpeechRecognitionAPI) {
    recognizer = new SpeechRecognitionAPI();
    recognizer.lang = "en-IN";
    recognizer.interimResults = false;
    recognizer.maxAlternatives = 1;

    recognizer.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        msgInput.value = transcript;
        sendMessage();
    };
    recognizer.onend = () => {
        listening = false;
        micBtn.classList.remove("listening");
    };
    recognizer.onerror = () => {
        listening = false;
        micBtn.classList.remove("listening");
    };
} else {
    micBtn.title = "Voice input not supported in this browser";
}

micBtn.addEventListener("click", () => {
    if (!recognizer) {
        alert("Your browser doesn't support voice input. Try Chrome or Edge.");
        return;
    }
    if (listening) {
        recognizer.stop();
        return;
    }
    currentMode = "voice";
    modePills.forEach((p) => p.classList.toggle("active", p.dataset.mode === "voice"));
    composerHint.textContent = "Listening…";
    listening = true;
    micBtn.classList.add("listening");
    recognizer.start();
});

// ---------------- Live autocomplete suggestions ----------------
function debounceSuggestions() {
    clearTimeout(suggestTimer);
    const partial = msgInput.value;
    if (partial.trim().length < 3) {
        suggestionsEl.innerHTML = "";
        return;
    }
    suggestTimer = setTimeout(() => fetchSuggestions(partial), 4000);
}

async function fetchSuggestions(partial) {
    try {
        const res = await fetch("/api/suggest", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ partial }),
        });
        const data = await res.json();
        renderSuggestions(data.suggestions || []);
    } catch (e) {
        // fail silently — suggestions are a nice-to-have
    }
}

function renderSuggestions(list) {
    suggestionsEl.innerHTML = "";
    list.forEach((s) => {
        const chip = document.createElement("div");
        chip.className = "suggestion-chip";
        chip.textContent = s;
        chip.addEventListener("click", () => {
            msgInput.value = s;
            suggestionsEl.innerHTML = "";
            msgInput.focus();
        });
        suggestionsEl.appendChild(chip);
    });
}

scrollToBottom();


const historyButtons = document.querySelectorAll(".history-item");

function appendBotPlaceholder() {
    const row = document.createElement("div");
    row.className = "msg msg-bot";

    const col = document.createElement("div");
    col.className = "bubble-col";

    const wrap = document.createElement("div");
    wrap.className = "bubble-wrap";

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = `<div class="typing-dots"><span></span><span></span><span></span></div>`;
    wrap.appendChild(bubble);

    const metaRow = document.createElement("div");
    metaRow.className = "bubble-meta-row";

    const actions = document.createElement("div");
    actions.className = "bubble-actions";

    const copyBtn = document.createElement("button");
    copyBtn.className = "bubble-action-btn";
    copyBtn.title = "Copy";
    copyBtn.textContent = "📋";
    copyBtn.style.display = "none";
    copyBtn.addEventListener("click", () => {
        navigator.clipboard.writeText(bubble.textContent);
        copyBtn.textContent = "✅";
        setTimeout(() => (copyBtn.textContent = "📋"), 1200);
    });
    actions.appendChild(copyBtn);

    const timeEl = document.createElement("div");
    timeEl.className = "bubble-time";

    metaRow.appendChild(actions);
    metaRow.appendChild(timeEl);
    col.appendChild(wrap);
    col.appendChild(metaRow);
    row.appendChild(col);
    chatScroll.appendChild(row);
    scrollToBottom();
    return { bubble, timeEl, copyBtn, col };
}

// ---------------- Blank "new chat" view (doesn't fetch, just clears screen) ----------------
function startNewChatView() {
    currentViewDate = "";
    historyButtons.forEach((b) => b.classList.remove("active"));
    const todayBtn = [...historyButtons].find((b) => b.dataset.date === "");
    if (todayBtn) todayBtn.classList.add("active");

    chatScroll.innerHTML =
        `<div class="empty-state"><div class="empty-mark">Fx</div><h2>${getGreeting()}</h2><p>Type, speak, or drop a file — Floxy handles all three.</p></div>`;
    document.querySelector(".composer").style.display = "block";
    msgInput.value = "";
    msgInput.focus();
}
document.getElementById("new-chat-btn").addEventListener("click", startNewChatView);

// ---------------- Load a specific day's full history ----------------
function loadHistoryForDate(dateStr) {
    currentViewDate = dateStr || "";
    historyButtons.forEach((b) => b.classList.remove("active"));
    const match = [...historyButtons].find((b) => b.dataset.date === (dateStr || ""));
    if (match) match.classList.add("active");

    return fetch(`/api/history?date=${dateStr || ""}`)
        .then((r) => r.json())
        .then((data) => {
            chatScroll.innerHTML = "";
            if (data.history.length === 0) {
                chatScroll.innerHTML = dateStr
                    ? `<div class="empty-state"><div class="empty-mark">Fx</div><h2>No messages on this day</h2></div>`
                    : `<div class="empty-state"><div class="empty-mark">Fx</div><h2>Kuch bhi pucho, ${FLOXY_NAME.split(" ")[0]}.</h2><p>Type, speak, or drop a file — Floxy handles all three.</p></div>`;
            } else {
                data.history.forEach((turn) => {
                    appendMessage("user", turn.user_message, turn.created_at);
                    appendMessage("bot", turn.bot_response, turn.created_at, turn.music_links, turn.file);
                });
            }
            scrollToBottom();
        });
}

historyButtons.forEach((btn) => {
    btn.addEventListener("click", () => loadHistoryForDate(btn.dataset.date));
});

// ---------------- Per-day kebab menu: Bookmark / Download / Delete ----------------
document.addEventListener("click", () => {
    document.querySelectorAll(".bookmark-menu.open").forEach((m) => m.classList.remove("open"));
});

document.querySelectorAll(".kebab-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const menu = btn.nextElementSibling;
        document.querySelectorAll(".bookmark-menu.open").forEach((m) => {
            if (m !== menu) m.classList.remove("open");
        });
        menu.classList.toggle("open");
    });
});

document.querySelectorAll(".bookmark-toggle-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const row = btn.closest(".history-row");
        const date = row.dataset.rowDate;
        const res = await fetch("/api/bookmark-day", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ date }),
        });
        const data = await res.json();
        const label = row.querySelector(".history-item");
        label.classList.toggle("bookmarked", data.bookmarked);
        const titleEl = label.querySelector(".hi-title");
        if (titleEl) {
            titleEl.textContent = (data.bookmarked ? "⭐ " : "") + titleEl.textContent.replace(/^⭐\s*/, "");
        }
        btn.closest(".bookmark-menu").classList.remove("open");
        loadBookmarkedDays();
    });
});

document.querySelectorAll(".pdf-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const date = btn.closest(".history-row").dataset.rowDate;
        window.open(`/api/export-pdf?date=${date}`, "_blank");
        btn.closest(".bookmark-menu").classList.remove("open");
    });
});

document.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const row = btn.closest(".history-row");
        const date = row.dataset.rowDate;
        if (!confirm(`Delete all chat from ${date}? This can't be undone.`)) return;
        await fetch(`/api/history/${date}`, { method: "DELETE" });
        row.remove();
        loadBookmarkedDays();
    });
});

// ---------------- Bookmarked days sidebar list ----------------
async function loadBookmarkedDays() {
    const res = await fetch("/api/bookmarked-days");
    const data = await res.json();
    const list = document.getElementById("bookmarks-list");
    list.innerHTML = "";
    data.days.forEach((d) => {
        const item = document.createElement("div");
        item.className = "history-item";
        item.style.cursor = "pointer";
        item.title = d.title;
        item.innerHTML =
            `<span class="hi-text"><span class="hi-title"></span><span class="hi-date"></span></span><span class="count"></span>`;
        item.querySelector(".hi-title").textContent = `⭐ ${d.title}`;
        item.querySelector(".hi-date").textContent = new Date(d.chat_date + "T00:00:00")
            .toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
        item.querySelector(".count").textContent = d.msg_count;
        item.addEventListener("click", () => loadHistoryForDate(d.chat_date));
        list.appendChild(item);
    });
}

loadBookmarkedDays();

// ---------------- Dynamic greeting ----------------
function getGreeting() {
    const hour = new Date().getHours();
    const firstName = FLOXY_NAME.split(" ")[0];
    const timeGreeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
    const options = [
        `${timeGreeting}, ${firstName}.`,
        `How can I help you today, ${firstName}?`,
        `Nice to see you, ${firstName}!`,
        `Welcome back, ${firstName}.`,
        `Ready when you are, ${firstName}.`,
        `Kuch bhi pucho, ${firstName}.`,
    ];
    return options[Math.floor(Math.random() * options.length)];
}

// ---------------- Theme switcher ----------------
const themeButtons = document.querySelectorAll(".theme-btn");
// ---------------- Theme switcher ----------------
const themeToggleBtn = document.getElementById("theme-toggle-btn");
const themePopover = document.getElementById("theme-popover");

themeToggleBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    themePopover.classList.toggle("open");
});
document.addEventListener("click", () => themePopover.classList.remove("open"));


function applyTheme(theme) {
    if (theme === "system") {
        document.documentElement.removeAttribute("data-theme");
    } else {
        document.documentElement.setAttribute("data-theme", theme);
    }
    localStorage.setItem("floxy-theme", theme);
    themeButtons.forEach((b) => b.classList.toggle("active", b.dataset.theme === theme));
}
themeButtons.forEach((btn) => {
    btn.addEventListener("click", () => applyTheme(btn.dataset.theme));
});
applyTheme(localStorage.getItem("floxy-theme") || "dark");


// ---------------- New chat ----------------
// document.getElementById("new-chat-btn").addEventListener("click", () => {
//     loadHistoryForDate("");
//     msgInput.value = "";
//     msgInput.focus();
// });


// ---------------- Mobile sidebar drawer ----------------
const mobileMenuBtn = document.getElementById("mobile-menu-btn");
const sidebarEl = document.querySelector(".sidebar");
const sidebarBackdrop = document.getElementById("sidebar-backdrop");

function toggleSidebar(open) {
    sidebarEl.classList.toggle("open", open);
    sidebarBackdrop.classList.toggle("open", open);
}

mobileMenuBtn.addEventListener("click", () => toggleSidebar(!sidebarEl.classList.contains("open")));
sidebarBackdrop.addEventListener("click", () => toggleSidebar(false));

// auto-close drawer after picking something on mobile
document.querySelectorAll(".history-item, .theme-btn, #new-chat-btn, .logout-link").forEach((el) => {
    el.addEventListener("click", () => {
        if (window.innerWidth <= 780) toggleSidebar(false);
    });
});


// ---------------- Desktop sidebar collapse ----------------
const sidebarToggleBtn = document.getElementById("sidebar-toggle-btn");
const appShell = document.querySelector(".app-shell");
sidebarToggleBtn.addEventListener("click", () => {
    const collapsed = appShell.classList.toggle("sidebar-collapsed");
    sidebarToggleBtn.textContent = collapsed ? "▶" : "◀";
    sidebarToggleBtn.classList.toggle("collapsed-pos", collapsed);
});


fetch("/api/history?date=")
    .then((r) => r.json())
    .then((data) => {
        if (data.history && data.history.length > 0) {
            loadHistoryForDate("");
        } else {
            startNewChatView();
        }
    })
    .catch(() => startNewChatView());

loadBookmarkedDays();

// ---------------- Poster maker ----------------
const posterModal = document.getElementById("poster-modal");
const posterForm = document.getElementById("poster-form");
const posterType = document.getElementById("pf-type");
const posterTitle = document.getElementById("pf-title");

const PF_FIELDS = {
    event:    ["subtitle", "details", "date", "venue", "contact"],
    sale:     ["subtitle", "highlight", "details", "date", "venue", "contact"],
    birthday: ["subtitle", "details", "date", "venue", "contact"],
    notice:   ["subtitle", "details", "date", "venue", "contact"],
    quote:    ["subtitle", "contact"],
    general:  ["subtitle", "details", "date", "venue", "contact"],
};
const PF_HINTS = {
    event:    { titleLabel: "Title", title: "e.g. Annual Tech Fest 2026", subLabel: "Subtitle", subPh: "e.g. Two days of coding and innovation" },
    sale:     { titleLabel: "Title", title: "e.g. Mega Diwali Sale", subLabel: "Subtitle", subPh: "e.g. On all electronics and appliances" },
    birthday: { titleLabel: "Title", title: "e.g. Happy Birthday Riya!", subLabel: "Subtitle", subPh: "e.g. Wishing you a year full of joy" },
    notice:   { titleLabel: "Title", title: "e.g. Library Timing Change", subLabel: "Subtitle", subPh: "e.g. Effective from Monday" },
    quote:    { titleLabel: "Quote", title: "Write the quote here", subLabel: "Author / name", subPh: "e.g. APJ Abdul Kalam" },
    general:  { titleLabel: "Title", title: "e.g. Floxy AI", subLabel: "Subtitle", subPh: "Optional line under the title" },
};

function wantsPoster(text) {
    const t = (text || "").toLowerCase();
    return /\b(poster|banner)\b/.test(t) &&
           /(bana|make|create|design|generate|chahiye|need|want)/.test(t);
}

function applyPosterType() {
    const t = posterType.value;
    const show = PF_FIELDS[t] || PF_FIELDS.general;
    posterForm.querySelectorAll(".pf-row").forEach((row) => {
        row.hidden = !show.includes(row.dataset.field);
    });
    const h = PF_HINTS[t] || PF_HINTS.general;
    document.getElementById("pf-title-label").textContent = h.titleLabel;
    document.getElementById("pf-sub-label").textContent = h.subLabel;
    posterTitle.placeholder = h.title;
    document.getElementById("pf-subtitle").placeholder = h.subPh;
}

function openPosterModal() {
    applyPosterType();
    posterModal.hidden = false;
    posterTitle.focus();
}
function closePosterModal() {
    posterModal.hidden = true;
}

posterType.addEventListener("change", applyPosterType);
document.getElementById("poster-close-btn").addEventListener("click", closePosterModal);
posterModal.addEventListener("click", (e) => { if (e.target === posterModal) closePosterModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !posterModal.hidden) closePosterModal(); });
document.getElementById("poster-open-btn").addEventListener("click", () => {
    openPosterModal();
    if (window.innerWidth <= 780) toggleSidebar(false);
});

posterForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(posterForm);
    const payload = {
        type: fd.get("type"),
        size: fd.get("size"),
        theme: fd.get("theme"),
        format: fd.get("format"),
        title: (fd.get("title") || "").trim(),
    };
    if (!payload.title) { posterTitle.focus(); return; }
    posterForm.querySelectorAll(".pf-row").forEach((row) => {
        if (!row.hidden) {
            const input = row.querySelector("input, textarea");
            payload[input.name] = (input.value || "").trim();
        }
    });

    closePosterModal();
    posterForm.reset();
    applyPosterType();

    if (currentViewDate !== "") await loadHistoryForDate("");
    appendMessage("user", `🎨 Poster: ${payload.title}`);
    const botMsg = appendBotPlaceholder();

    try {
        const res = await fetch("/api/poster", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (res.ok && data.file) {
            botMsg.bubble.textContent = data.reply;
            renderSavedFile(botMsg.col, data.file);
        } else {
            botMsg.bubble.textContent = data.error || "Poster nahi ban paya.";
        }
    } catch (err) {
        botMsg.bubble.textContent = "Network error — please try again.";
    }
    botMsg.timeEl.textContent = formatRelativeTime(new Date());
    botMsg.copyBtn.style.display = "";
    scrollToBottom();
});