const ACTIVE_CONVERSATION_KEY = "aios-active-conversation";
const ACTIVE_STREAM_KEY = "aios-active-stream";
const ACTIVE_THREAD_KEY = "aios-active-thread";

let activeConversationId = localStorage.getItem(ACTIVE_CONVERSATION_KEY) || null;
let activeThreadId = localStorage.getItem(ACTIVE_THREAD_KEY) || "main";
let activeSessionId = localStorage.getItem("aios-session-id") || "";
let lastAssistantText = "";
let recognition = null;
let speechSynthesisSupported = "speechSynthesis" in window;
let streamController = null;
let selectedFiles = [];

const messages = document.querySelector("#messages");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const conversationList = document.querySelector("#conversation-list");
const newChat = document.querySelector("#new-chat");
const searchChatsButton = document.querySelector("#search-chats");
const chatSearchDialog = document.querySelector("#chat-search-dialog");
const chatSearchForm = document.querySelector("#chat-search-form");
const chatSearchQuery = document.querySelector("#chat-search-query");
const chatSearchStatus = document.querySelector("#chat-search-status");
const chatSearchResults = document.querySelector("#chat-search-results");
const closeChatSearch = document.querySelector("#close-chat-search");
const voiceInputButton = document.querySelector("#voice-input");
const voiceOutputButton = document.querySelector("#voice-output");
const sendMessageButton = document.querySelector("#send-message");
const themeSelect = document.querySelector("#theme-select");
const fileInput = document.querySelector("#file-input");
const dropZone = document.querySelector("#drop-zone");
const attachmentCount = document.querySelector("#attachment-count");
const artifactList = document.querySelector("#artifact-list");
const refreshArtifacts = document.querySelector("#refresh-artifacts");
const refreshObservability = document.querySelector("#refresh-observability");
const observabilityDashboard = document.querySelector("#observability-dashboard");
const providerMode = document.querySelector("#provider-mode");
const contextWindow = document.querySelector("#context-window");
const compactMode = document.querySelector("#compact-mode");
const profileName = document.querySelector("#profile-name");
const profileRole = document.querySelector("#profile-role");
const workspaceName = document.querySelector("#workspace-name");
const workspaceFocus = document.querySelector("#workspace-focus");
const runningTask = document.querySelector("#running-task");
const activeFile = document.querySelector("#active-file");
const activeTool = document.querySelector("#active-tool");
const terminalOutput = document.querySelector("#terminal-output");
const browserResults = document.querySelector("#browser-results");
const mcpOutputs = document.querySelector("#mcp-outputs");
const developerInstructions = document.querySelector("#developer-instructions");
const threadSelect = document.querySelector("#thread-select");
const newThread = document.querySelector("#new-thread");
const notificationList = document.querySelector("#notification-list");
const mobileTools = document.querySelector("#mobile-tools");
const toolsToggle = document.querySelector("#tools-toggle");
const closeTools = document.querySelector("#close-tools");
const emptyState = document.querySelector("#empty-state");
const authDialog = document.querySelector("#auth-dialog");
const authForm = document.querySelector("#auth-form");
const authName = document.querySelector("#auth-name");
const authEmail = document.querySelector("#auth-email");
const authPassword = document.querySelector("#auth-password");
const authStatus = document.querySelector("#auth-status");
const accountLabel = document.querySelector("#account-label");
const signOutButton = document.querySelector("#sign-out");
let requestedAuthMode = "login";
let authenticationResolver = null;

function storeAuthentication(payload) {
  localStorage.setItem("aios-access-token", payload.access_token);
  if (payload.session?.id) setActiveSession(payload.session.id);
  accountLabel.textContent = payload.user?.display_name || payload.user?.email || "Account";
  accountLabel.hidden = false;
  signOutButton.hidden = false;
}

function clearAuthentication() {
  localStorage.removeItem("aios-access-token");
  localStorage.removeItem("aios-session-id");
  activeSessionId = "";
  accountLabel.hidden = true;
  signOutButton.hidden = true;
}

function requestAuthentication(message = "") {
  authStatus.textContent = message;
  if (!authDialog.open) authDialog.showModal();
  authEmail.focus();
  return new Promise((resolve) => { authenticationResolver = resolve; });
}

async function ensureAuthenticated() {
  const token = localStorage.getItem("aios-access-token") || "";
  if (token) {
    try {
      const response = await authenticatedFetch("/api/v1/auth/me");
      if (response.ok) {
        const payload = await response.json();
        accountLabel.textContent = payload.user?.display_name || payload.user?.email || "Account";
        accountLabel.hidden = false;
        signOutButton.hidden = false;
        return true;
      }
    } catch (error) { console.error("Could not validate saved login", error); }
    clearAuthentication();
  }
  return requestAuthentication(token ? "Your session expired. Please sign in again." : "");
}

async function submitAuthentication(mode) {
  const email = authEmail.value.trim();
  const password = authPassword.value;
  const displayName = authName.value.trim();
  if (mode === "register" && !displayName) {
    authStatus.textContent = "Enter your name to create an account.";
    authName.focus();
    return;
  }
  authStatus.textContent = mode === "register" ? "Signing up..." : "Logging in...";
  const requestBody = { email, password };
  if (mode === "register") requestBody.display_name = displayName;
  authForm.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    const response = await window.fetch(`/api/v1/auth/${mode}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
    const payload = await response.json();
    if (!response.ok) { authStatus.textContent = shortError(payload.error || "Authentication failed."); return; }
    storeAuthentication(payload);
    authStatus.textContent = "";
    authPassword.value = "";
    authDialog.close();
    authenticationResolver?.(true);
    authenticationResolver = null;
  } catch (error) {
    authStatus.textContent = shortError(error.message || "Could not reach the server.");
  } finally {
    authForm.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  }
}

authForm.addEventListener("click", (event) => {
  const button = event.target.closest("[data-auth-mode]");
  if (button) requestedAuthMode = button.dataset.authMode;
});
authForm.addEventListener("submit", async (event) => { event.preventDefault(); await submitAuthentication(requestedAuthMode); });
authDialog.addEventListener("cancel", (event) => event.preventDefault());
signOutButton.addEventListener("click", () => { clearAuthentication(); window.location.reload(); });

function applyTheme(theme) {
  const resolvedTheme = theme === "dark" ? "dark" : "light";
  document.body.setAttribute("data-theme", resolvedTheme);
  if (themeSelect) {
    themeSelect.value = resolvedTheme;
  }
  localStorage.setItem("aios-theme", resolvedTheme);
}

const savedTheme = localStorage.getItem("aios-theme");
applyTheme(savedTheme || "dark");

if (themeSelect) {
  themeSelect.addEventListener("change", (event) => {
    applyTheme(event.target.value);
  });
}

loadPreferences();

if (fileInput) {
  fileInput.addEventListener("change", () => {
    addSelectedFiles(Array.from(fileInput.files || []));
    fileInput.value = "";
  });
}

if (dropZone) {
  ["dragenter", "dragover"].forEach((name) => {
    dropZone.addEventListener(name, (event) => {
      event.preventDefault();
      dropZone.classList.add("dragging");
    });
  });

  ["dragleave", "drop"].forEach((name) => {
    dropZone.addEventListener(name, () => dropZone.classList.remove("dragging"));
  });

  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    addSelectedFiles(Array.from(event.dataTransfer.files || []));
  });
}

refreshArtifacts.addEventListener("click", loadArtifacts);
refreshObservability?.addEventListener("click", loadObservability);
newThread.addEventListener("click", createThread);
threadSelect.addEventListener("change", () => {
  setActiveThread(threadSelect.value || "main");
  if (activeConversationId) {
    openConversation(activeConversationId);
  }
});
mobileTools.addEventListener("click", () => document.body.classList.toggle("tools-open"));
toolsToggle.addEventListener("click", () => document.body.classList.toggle("tools-open"));
closeTools.addEventListener("click", () => document.body.classList.remove("tools-open"));

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
});

[providerMode, contextWindow, compactMode, profileName, profileRole, workspaceName, workspaceFocus, runningTask, activeFile, activeTool, terminalOutput, browserResults, mcpOutputs, developerInstructions].forEach((control) => {
  control.addEventListener("change", savePreferences);
  control.addEventListener("input", savePreferences);
});

if (window.SpeechRecognition || window.webkitSpeechRecognition) {
  const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognitionCtor();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = "en-US";

  recognition.onresult = (event) => {
    const transcript = Array.from(event.results)
      .map((result) => result[0].transcript)
      .join(" ");
    input.value = transcript;
    input.focus();
    voiceInputButton.classList.remove("active");

    if (transcript.trim()) {
      form.requestSubmit();
    }
  };

  recognition.onerror = () => {
    voiceInputButton.classList.remove("active");
  };
}

voiceInputButton.addEventListener("click", () => {
  if (!recognition) {
    updateMessage(appendMessage("assistant", "Voice input is not supported in this browser."), "");
    return;
  }

  if (voiceInputButton.classList.contains("active")) {
    recognition.stop();
    voiceInputButton.classList.remove("active");
    return;
  }

  voiceInputButton.classList.add("active");
  recognition.start();
});

voiceOutputButton.addEventListener("click", () => {
  if (!speechSynthesisSupported || !lastAssistantText) {
    updateMessage(appendMessage("assistant", "Speech output is not available in this browser."), "");
    return;
  }

  const utterance = new SpeechSynthesisUtterance(lastAssistantText);
  utterance.lang = "en-US";
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (streamController) {
    streamController.abort();
    return;
  }

  let content = input.value.trim();
  if (!content && selectedFiles.length) {
    content = "Please review the attached files.";
  }
  if (!content) return;

  input.value = "";
  input.style.height = "auto";
  input.disabled = true;
  setComposerBusy(true);
  const attachments = selectedFiles.slice();
  selectedFiles = [];
  updateAttachmentCount();
  lastAssistantText = "";
  appendMessage("user", attachments.length ? `${content}\n\n${fileSummary(attachments)}` : content);
  const pending = appendMessage("assistant", "");
  setMessageProcessing(pending, "Preparing request");
  streamController = new AbortController();
  setResponseActive(true);

  try {
    const uploadedArtifacts = attachments.length ? await uploadFiles(attachments) : [];
    if (uploadedArtifacts.length) {
      notify("Uploads ready", `${uploadedArtifacts.length} artifact(s) attached to this message.`);
      await loadArtifacts();
    }
    const response = await authenticatedFetch("/api/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: activeSessionId,
        conversation_id: activeConversationId,
        thread_id: activeThreadId,
        artifact_ids: uploadedArtifacts.map((artifact) => artifact.id),
        message: content,
        stream: true,
      }),
      signal: streamController.signal,
    });

    if (!response.ok) {
      const payload = await response.json();
      updateMessage(pending, `Error: ${shortError(payload.error || "Something went wrong.")}`);
      return;
    }

    await readChatStream(response, pending);
    lastAssistantText = pending.textContent || "";
    localStorage.removeItem(ACTIVE_STREAM_KEY);
    await loadConversations();
    notify("Reply complete", "The assistant response finished streaming.");
  } catch (error) {
    if (error.name === "AbortError") {
      updateMessage(pending, `${lastAssistantText || "Response"}\n\n[Response stopped.]`);
      await recoverInterruptedStream();
      notify("Stream stopped", "The current response was cancelled.");
    } else {
      updateMessage(pending, `Error: ${shortError(error.message || "Could not reach the local AIOS server.")}`);
      await recoverInterruptedStream();
      notify("Chat error", shortError(error.message || "Could not reach the local AIOS server."));
    }
  } finally {
    input.disabled = false;
    setComposerBusy(false);
    input.focus();
    streamController = null;
    setResponseActive(false);
  }
});

function openChatSearch() {
  chatSearchDialog.showModal();
  chatSearchQuery.focus();
  chatSearchQuery.select();
}

function closeChatSearchDialog() {
  chatSearchDialog.close();
}

function renderChatSearchResults(results) {
  chatSearchResults.innerHTML = "";
  if (!results.length) {
    chatSearchStatus.textContent = "No semantically related chats were found.";
    return;
  }

  chatSearchStatus.textContent = results.length + " related chat" + (results.length === 1 ? "" : "s") + " found.";
  results.forEach((result) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chat-search-result";

    const title = document.createElement("strong");
    title.textContent = result.title || "New chat";
    const snippet = document.createElement("span");
    snippet.textContent = result.snippet || "Matching conversation";
    const metadata = document.createElement("small");
    const updated = result.updated_at ? new Date(result.updated_at) : null;
    metadata.textContent = updated && !Number.isNaN(updated.getTime())
      ? "Semantic match · " + updated.toLocaleString()
      : "Semantic match";

    button.append(title, snippet, metadata);
    button.addEventListener("click", async () => {
      try {
        await openConversation(result.conversation_id);
        closeChatSearchDialog();
        document.body.classList.remove("sidebar-open");
      } catch (error) {
        chatSearchStatus.textContent = shortError(error);
      }
    });
    chatSearchResults.appendChild(button);
  });
}

async function searchPreviousChats(query) {
  const text = query.trim();
  if (!text) {
    chatSearchStatus.textContent = "Enter a phrase or describe the conversation you want to retrieve.";
    chatSearchResults.innerHTML = "";
    return;
  }

  chatSearchStatus.textContent = "Searching previous chats by meaning…";
  chatSearchResults.innerHTML = "";
  try {
    const url = "/api/v1/conversations/search?q=" + encodeURIComponent(text) + "&top_k=10";
    const response = await authenticatedFetch(url);
    const payload = await response.json();
    if (!response.ok) throw new Error(shortError(payload.error || "Chat search failed."));
    renderChatSearchResults(payload.results || []);
  } catch (error) {
    chatSearchStatus.textContent = "Search error: " + shortError(error);
  }
}

searchChatsButton.addEventListener("click", openChatSearch);
closeChatSearch.addEventListener("click", closeChatSearchDialog);
chatSearchDialog.addEventListener("click", (event) => {
  if (event.target === chatSearchDialog) closeChatSearchDialog();
});
chatSearchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  searchPreviousChats(chatSearchQuery.value);
});
newChat.addEventListener("click", async () => {
  setActiveConversation(null);
  setActiveThread("main");
  messages.innerHTML = "";
  selectedFiles = [];
  updateAttachmentCount();
  updateEmptyState();
  localStorage.removeItem(ACTIVE_STREAM_KEY);
  input.value = "";
  input.style.height = "auto";
  input.focus();
});

async function loadConversations() {
  // Recent chat history is account-wide for this local single-user app. Sessions
  // scope working context, but must not hide persisted conversations after a
  // browser restart, local-storage reset, or migration from pre-session data.
  const response = await authenticatedFetch("/api/v1/conversations");
  const payload = await response.json();
  const conversations = payload.conversations || [];
  conversationList.innerHTML = "";

  conversations.forEach((conversation) => {
    const item = document.createElement("div");
    item.className = "conversation-item";
    const button = document.createElement("button");
    button.className = "secondary";
    const title = String(conversation.title || "New chat").trim() || "New chat";
    button.textContent = title;
    button.title = title;
    button.dataset.conversationId = conversation.id;
    button.classList.toggle("active", conversation.id === activeConversationId);
    button.setAttribute("aria-current", conversation.id === activeConversationId ? "page" : "false");
    button.addEventListener("click", () => openConversation(conversation.id));

    const menuButton = document.createElement("button");
    menuButton.className = "conversation-menu-button";
    menuButton.type = "button";
    menuButton.textContent = "•••";
    menuButton.title = "Actions for " + title;
    menuButton.setAttribute("aria-label", "Actions for " + title);
    menuButton.addEventListener("click", (event) => {
      event.stopPropagation();
      const willOpen = !item.classList.contains("menu-open");
      closeConversationMenus();
      item.classList.toggle("menu-open", willOpen);
    });

    const menu = document.createElement("div");
    menu.className = "conversation-menu";
    menu.innerHTML = '<button type="button" data-action="rename">Rename</button><button type="button" data-action="delete" class="danger-menu-item">Delete</button>';
    menu.querySelector('[data-action="rename"]').addEventListener("click", () => renameConversation(conversation));
    menu.querySelector('[data-action="delete"]').addEventListener("click", () => deleteConversation(conversation));
    item.append(button, menuButton, menu);
    conversationList.appendChild(item);
  });
  return conversations;
}

function closeConversationMenus() {
  conversationList.querySelectorAll(".conversation-item.menu-open").forEach((item) => item.classList.remove("menu-open"));
}

async function renameConversation(conversation) {
  closeConversationMenus();
  const title = window.prompt("Rename chat", conversation.title || "New chat");
  if (title === null) return;
  const normalized = title.trim();
  if (!normalized) {
    notify("Rename failed", "Chat name cannot be empty.");
    return;
  }
  const response = await authenticatedFetch("/api/v1/conversations/" + conversation.id, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: normalized }),
  });
  const payload = await response.json();
  if (!response.ok) {
    notify("Rename failed", shortError(payload.error || "Could not rename chat."));
    return;
  }
  await loadConversations();
}

async function deleteConversation(conversation) {
  closeConversationMenus();
  if (!window.confirm('Delete "' + (conversation.title || "New chat") + '"? This cannot be undone.')) return;
  const response = await authenticatedFetch("/api/v1/conversations/" + conversation.id, { method: "DELETE" });
  const payload = await response.json();
  if (!response.ok) {
    notify("Delete failed", shortError(payload.error || "Could not delete chat."));
    return;
  }
  if (activeConversationId === conversation.id) {
    setActiveConversation(null);
    setActiveThread("main");
    messages.innerHTML = "";
    updateEmptyState();
  }
  await loadConversations();
}

document.addEventListener("click", (event) => {
  if (!event.target.closest(".conversation-item")) closeConversationMenus();
});

async function openConversation(id) {
  const response = await authenticatedFetch(`/api/v1/conversations/${id}`);
  if (!response.ok) {
    setActiveConversation(null);
    throw new Error("Conversation not found.");
  }
  const conversation = await response.json();
  setActiveConversation(id);
  conversationList.querySelectorAll("[data-conversation-id]").forEach((button) => {
    const isActive = button.dataset.conversationId === id;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-current", isActive ? "page" : "false");
  });
  setActiveThread(activeThreadId || conversation.active_thread_id || "main");
  localStorage.removeItem(ACTIVE_STREAM_KEY);
  messages.innerHTML = "";
  renderThreads(conversation);
  conversation.messages
    .filter((message) => (message.thread_id || "main") === activeThreadId)
    .forEach((message) => appendMessage(message.role, message.content));
  updateEmptyState();
}

async function readChatStream(response, pending) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let assistantText = "";
  let provider = "";
  let progressText = "";

  const processChunk = (chunk) => {
    const lines = chunk.split(/\n+/);
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const event = JSON.parse(trimmed);
        if (event.type === "meta") {
          if (event.session_id) {
            setActiveSession(event.session_id);
          }
          if (event.context_token_count && event.context_window_tokens) {
            notify("Context ready", `${event.context_token_count}/${event.context_window_tokens} estimated tokens.`);
          }
          setActiveConversation(event.conversation_id);
          setActiveThread(event.thread_id || activeThreadId || "main");
          provider = event.provider || "";
          localStorage.setItem(ACTIVE_STREAM_KEY, activeConversationId);
          setMessageProcessing(pending, progressText || "Preparing stream", provider);
        } else if (event.type === "progress") {
          progressText = event.message || event.stage || "";
          if (assistantText) {
            updateMessage(pending, assistantText, provider, progressText, true);
          } else {
            setMessageProcessing(pending, progressText, provider);
          }
        } else if (event.type === "delta") {
          assistantText += event.content || "";
          updateMessage(pending, assistantText, provider, progressText, true);
        } else if (event.type === "done") {
          progressText = "";
          localStorage.removeItem(ACTIVE_STREAM_KEY);
          updateMessage(pending, event.message.content || assistantText, provider);
        } else if (event.type === "error") {
          throw new Error(event.error || "Streaming failed.");
        }
      } catch (parseError) {
        if (parseError instanceof SyntaxError) {
          console.error("Invalid stream event", trimmed, parseError);
        } else {
          throw parseError;
        }
      }
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    const lastNewline = buffer.lastIndexOf("\n");
    if (lastNewline >= 0) {
      const completeChunk = buffer.slice(0, lastNewline);
      processChunk(completeChunk);
      buffer = buffer.slice(lastNewline + 1);
    }

    if (done) {
      if (buffer.trim()) {
        processChunk(buffer);
      }
      break;
    }
  }
}

function appendMessage(role, content) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  article.innerHTML = messageHtml(role, content);
  messages.appendChild(article);
  messages.scrollTop = messages.scrollHeight;
  updateEmptyState();
  return article;
}

function updateMessage(article, content, provider = "", progress = "", isStreaming = false) {
  const role = "assistant";
  article.classList.toggle("streaming", isStreaming);
  article.classList.remove("processing");
  article.innerHTML = messageHtml(role, content, progress, isStreaming);
  messages.scrollTop = messages.scrollHeight;
  if (role.startsWith("assistant")) {
    lastAssistantText = content;
  }
  updateEmptyState();
}

function setMessageProcessing(article, status, provider = "") {
  const role = "assistant";
  article.classList.add("processing");
  article.classList.remove("streaming");
  article.innerHTML = processingHtml(role, status);
  messages.scrollTop = messages.scrollHeight;
  updateEmptyState();
}

function updateEmptyState() {
  emptyState.hidden = Boolean(messages.children.length);
}

function messageHtml(role, content, progress = "", isStreaming = false) {
  const cursor = isStreaming ? '<span class="stream-cursor"></span>' : "";
  const progressHtml = progress ? `<div class="stream-progress">${escapeHtml(progress)}</div>` : "";
  return `<strong class="role">${escapeHtml(role)}</strong><div class="message-content">${renderMarkdown(content)}${cursor}</div>${progressHtml}`;
}

function processingHtml(role, status) {
  const progressHtml = `<div class="stream-progress">${escapeHtml(status || "Processing")}</div>`;
  return `<strong class="role">${escapeHtml(role)}</strong><div class="message-content"><span class="typing-dots"><span></span><span></span><span></span></span></div>${progressHtml}`;
}

function renderMarkdown(value) {
  const blocks = [];
  const mathBlocks = [];
  let source = String(value || "").replace(/```(\w+)?\n?([\s\S]*?)```/g, (_, language, code) => {
    const token = `@@CODE${blocks.length}@@`;
    blocks.push(`<pre><code data-language="${escapeHtml(language || "text")}">${highlightCode(code.trim(), language || "")}</code></pre>`);
    return token;
  });
  source = source
    .replace(/\\\[([\s\S]*?)\\\]/g, (_, expression) => protectMath(expression, true, mathBlocks))
    .replace(/\$\$([\s\S]*?)\$\$/g, (_, expression) => protectMath(expression, true, mathBlocks))
    .replace(/\\\(([\s\S]*?)\\\)/g, (_, expression) => protectMath(expression, false, mathBlocks))
    .replace(/(^|[^\\$])\$([^$\n]+?)\$/g, (_, prefix, expression) => `${prefix}${protectMath(expression, false, mathBlocks)}`);

  let escaped = escapeHtml(source);
  escaped = escaped
    .replace(/^### (.*)$/gm, "<h3>$1</h3>")
    .replace(/^## (.*)$/gm, "<h2>$1</h2>")
    .replace(/^# (.*)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.*?)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
    .replace(/^- (.*)$/gm, "<li>$1</li>")
    .replace(/\n/g, "<br>");

  escaped = escaped.replace(/(<li>.*?<\/li>(?:<br><li>.*?<\/li>)*)/g, (match) => {
    return `<ul>${match.replace(/<br>/g, "")}</ul>`;
  });

  blocks.forEach((html, index) => {
    escaped = escaped.replace(`@@CODE${index}@@`, html);
  });
  mathBlocks.forEach((html, index) => {
    escaped = escaped.replace(`@@MATH${index}@@`, html);
  });
  return escaped;
}

function protectMath(expression, displayMode, mathBlocks) {
  const token = `@@MATH${mathBlocks.length}@@`;
  mathBlocks.push(renderMath(expression, displayMode));
  return token;
}

function renderMath(expression, displayMode = false) {
  const latex = String(expression || "").trim();
  if (!latex) return "";
  if (window.katex?.renderToString) {
    try {
      return window.katex.renderToString(latex, {
        displayMode,
        throwOnError: false,
        strict: "ignore",
        output: "html",
      });
    } catch (_error) {
      // Fall through to a readable escaped formula if KaTeX rejects the input.
    }
  }
  const tag = displayMode ? "div" : "span";
  return `<${tag} class="math-fallback">${escapeHtml(latex)}</${tag}>`;
}

function highlightCode(code, language) {
  let highlighted = escapeHtml(code);
  highlighted = highlighted.replace(/(&quot;.*?&quot;|&#039;.*?&#039;)/g, '<span class="syntax-string">$1</span>');
  const keywordSets = {
    py: "def|class|return|import|from|if|elif|else|for|while|try|except|with|as|True|False|None",
    python: "def|class|return|import|from|if|elif|else|for|while|try|except|with|as|True|False|None",
    js: "function|const|let|var|return|import|export|if|else|for|while|try|catch|await|async|new",
    javascript: "function|const|let|var|return|import|export|if|else|for|while|try|catch|await|async|new",
    json: "true|false|null",
  };
  const pattern = keywordSets[String(language).toLowerCase()];
  if (pattern) {
    highlighted = highlighted.replace(new RegExp(`\\b(${pattern})\\b`, "g"), '<span class="syntax-keyword">$1</span>');
  }
  return highlighted;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };
    return map[char];
  });
}

function shortError(value) {
  const message = typeof value === "string" ? value : value?.message || JSON.stringify(value);
  return message.length > 700 ? `${message.slice(0, 700)}...` : message;
}

function authenticatedFetch(url, options = {}) {
  const token = localStorage.getItem("aios-access-token") || "";
  const headers = { ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  return window.fetch(url, { ...options, headers });
}

function addSelectedFiles(files) {
  selectedFiles = [...selectedFiles, ...files].slice(0, 8);
  updateAttachmentCount();
  if (files.length) {
    notify("Files selected", `${files.length} file(s) ready to attach.`);
  }
}

function updateAttachmentCount() {
  attachmentCount.textContent = selectedFiles.length ? `${selectedFiles.length} file${selectedFiles.length === 1 ? "" : "s"}` : "";
}

function fileSummary(files) {
  return files.map((file) => `- ${file.name} (${formatBytes(file.size)})`).join("\n");
}

async function uploadFiles(files) {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  const response = await authenticatedFetch("/api/v1/uploads", { method: "POST", body: formData });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(shortError(payload.error || "Upload failed."));
  }
  return payload.artifacts || [];
}

async function loadArtifacts() {
  const response = await authenticatedFetch("/api/v1/uploads");
  const payload = await response.json();
  renderArtifacts(payload.artifacts || []);
}

async function loadObservability() {
  if (!observabilityDashboard) return;
  try {
    const response = await authenticatedFetch("/api/v1/observability");
    const payload = await response.json();
    if (!response.ok) throw new Error(shortError(payload.error || "Observability unavailable."));
    const data = payload.observability || {};
    const resources = data.resources || {};
    const queues = data.queues?.totals || {};
    const gpu = data.gpu?.available ? `${data.gpu.gpus.length} GPU` : "Not detected";
    const metrics = [
      ["Status", data.status || "unknown", `status-${data.status || "degraded"}`],
      ["API p95", `${Number(data.api?.p95_latency_ms || 0).toFixed(1)} ms`, ""],
      ["Tokens", Number(data.tokens?.total || 0).toLocaleString(), ""],
      ["Estimated cost", `$${Number(data.cost?.estimated_usd || 0).toFixed(4)}`, ""],
      ["Model success", `${(Number(data.models?.success_rate || 0) * 100).toFixed(1)}%`, ""],
      ["Tool success", `${(Number(data.tools?.success_rate || 0) * 100).toFixed(1)}%`, ""],
      ["CPU", resources.available ? `${Number(resources.cpu_percent || 0).toFixed(1)}%` : "Unavailable", ""],
      ["Memory", resources.available ? `${Number(resources.memory_percent || 0).toFixed(1)}%` : "Unavailable", ""],
      ["GPU", gpu, ""],
      ["Queue pending", Number(queues.pending || 0).toLocaleString(), ""],
      ["Errors", Number(data.errors?.count || 0).toLocaleString(), ""],
      ["Users", Number(data.users?.unique_users || 0).toLocaleString(), ""],
    ];
    observabilityDashboard.innerHTML = metrics.map(([label, value, className]) => `<div class="metric-card ${className}"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></div>`).join("");
  } catch (error) {
    observabilityDashboard.innerHTML = `<div class="metric-card status-degraded"><small>Observability</small><strong>${escapeHtml(shortError(error))}</strong></div>`;
  }
}
async function ensureSession() {
  const query = activeSessionId ? `?session_id=${encodeURIComponent(activeSessionId)}` : "";
  const response = await authenticatedFetch(`/api/v1/session${query}`);
  const payload = await response.json();
  if (payload.session && payload.session.id) {
    setActiveSession(payload.session.id);
    applySessionContext(payload.session);
  }
}

function setActiveSession(sessionId) {
  activeSessionId = sessionId;
  localStorage.setItem("aios-session-id", sessionId);
}

function setActiveConversation(conversationId) {
  activeConversationId = conversationId || null;
  if (activeConversationId) {
    localStorage.setItem(ACTIVE_CONVERSATION_KEY, activeConversationId);
  } else {
    localStorage.removeItem(ACTIVE_CONVERSATION_KEY);
  }
}

function setActiveThread(threadId) {
  activeThreadId = threadId || "main";
  localStorage.setItem(ACTIVE_THREAD_KEY, activeThreadId);
  if (threadSelect) {
    threadSelect.value = activeThreadId;
  }
}

function renderThreads(conversation) {
  if (!threadSelect) {
    return;
  }
  const threads = conversation.threads && conversation.threads.length ? conversation.threads : [{ id: "main", title: "Main" }];
  if (!threads.some((thread) => thread.id === activeThreadId)) {
    setActiveThread(conversation.active_thread_id || threads[0].id);
  }
  threadSelect.innerHTML = threads
    .map((thread) => `<option value="${escapeHtml(thread.id)}">${escapeHtml(thread.title || "Thread")}</option>`)
    .join("");
  threadSelect.value = activeThreadId;
}

async function createThread() {
  if (!activeConversationId) {
    notify("No conversation", "Start or open a conversation before creating a thread.");
    return;
  }
  const response = await authenticatedFetch(`/api/v1/conversations/${activeConversationId}/threads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: `Thread ${new Date().toLocaleTimeString()}` }),
  });
  const thread = await response.json();
  if (!response.ok) {
    notify("Thread error", shortError(thread.error || "Could not create thread."));
    return;
  }
  setActiveThread(thread.id);
  messages.innerHTML = "";
  updateEmptyState();
  await openConversation(activeConversationId);
}

function applySessionContext(session) {
  const localWorkspace = loadJson("aios-workspace", {});
  const localSettings = loadJson("aios-settings", {});
  const preferences = session.user_preferences || {};
  const workspace = session.current_workspace || {};
  const activeProject = session.active_project || workspace.name || "";
  if (!localSettings.providerMode && preferences.provider_mode) {
    providerMode.value = preferences.provider_mode;
  }
  if (!localSettings.contextWindow && preferences.context_window_tokens) {
    contextWindow.value = preferences.context_window_tokens;
  }
  if (localSettings.compactMode === undefined && preferences.compact_mode !== undefined) {
    compactMode.checked = Boolean(preferences.compact_mode);
  }
  if (!localWorkspace.name && activeProject) {
    workspaceName.value = activeProject;
  }
  if (!localWorkspace.focus && workspace.focus) {
    workspaceFocus.value = workspace.focus;
  }
  if (!localWorkspace.runningTask && session.running_task) {
    runningTask.value = session.running_task;
  }
  if (!localWorkspace.activeFile && session.active_file) {
    activeFile.value = session.active_file;
  }
  if (!localWorkspace.activeTool && session.active_tool) {
    activeTool.value = session.active_tool;
  }
  if (!localWorkspace.terminalOutput && session.terminal_output) {
    terminalOutput.value = session.terminal_output;
  }
  if (!localWorkspace.browserResults && session.browser_results) {
    browserResults.value = session.browser_results;
  }
  if (!localWorkspace.mcpOutputs && session.mcp_outputs) {
    mcpOutputs.value = session.mcp_outputs;
  }
  if (!localWorkspace.developerInstructions && session.developer_instructions) {
    developerInstructions.value = session.developer_instructions;
  }
  savePreferences({ persistSession: false });
}

function renderArtifacts(artifacts) {
  artifactList.innerHTML = "";
  if (!artifacts.length) {
    artifactList.innerHTML = '<div class="artifact"><small>No artifacts yet.</small></div>';
    return;
  }
  artifacts.slice(0, 12).forEach((item) => {
    const card = document.createElement("article");
    card.className = "artifact";
    const url = `/api/uploads/${item.id}/content`;
    const textPreview = item.cleaned_text || item.extracted_text || item.preview || "";
    const ocrStatus = item.ocr_status ? `<small>OCR: ${escapeHtml(item.ocr_status)}</small>` : "";
    const metadata = item.metadata || {};
    const chunkCount = metadata.chunk_count || (item.chunks ? item.chunks.length : 0);
    const chunkStatus = chunkCount ? `<small>${chunkCount} chunk${chunkCount === 1 ? "" : "s"}</small>` : "";
    const vectorCount = metadata.vector_count || 0;
    const vectorStatus = vectorCount ? `<small>${vectorCount} vector${vectorCount === 1 ? "" : "s"}</small>` : "";
    const preview =
      item.category === "image"
        ? `<img src="${url}" alt="${escapeHtml(item.filename)}" />`
        : item.category === "audio"
          ? `<audio src="${url}" controls></audio>`
          : item.category === "pdf"
            ? `<a href="${url}" target="_blank" rel="noreferrer">Open PDF</a>`
            : textPreview
              ? `<small>${escapeHtml(textPreview.slice(0, 160))}</small>`
              : "";
    const extractedPreview =
      item.category === "image" || item.category === "pdf"
        ? textPreview
          ? `<small>${escapeHtml(textPreview.slice(0, 160))}</small>`
          : ""
        : "";
    card.innerHTML = `<strong>${escapeHtml(item.filename)}</strong><small>${item.category} - ${formatBytes(item.size)}</small>${ocrStatus}${chunkStatus}${vectorStatus}${preview}${extractedPreview}`;
    artifactList.appendChild(card);
  });
}

function loadPreferences() {
  const settings = loadJson("aios-settings", {});
  const profile = loadJson("aios-profile", {});
  const workspace = loadJson("aios-workspace", {});
  providerMode.value = settings.providerMode || "auto";
  contextWindow.value = settings.contextWindow || 4000;
  compactMode.checked = Boolean(settings.compactMode);
  profileName.value = profile.name || "";
  profileRole.value = profile.role || "";
  workspaceName.value = workspace.name || "";
  workspaceFocus.value = workspace.focus || "";
  runningTask.value = workspace.runningTask || "";
  activeFile.value = workspace.activeFile || "";
  activeTool.value = workspace.activeTool || "";
  terminalOutput.value = workspace.terminalOutput || "";
  browserResults.value = workspace.browserResults || "";
  mcpOutputs.value = workspace.mcpOutputs || "";
  developerInstructions.value = workspace.developerInstructions || "";
  document.body.classList.toggle("compact", compactMode.checked);
}

function savePreferences(options = {}) {
  const persistSession = options.persistSession !== false;
  localStorage.setItem(
    "aios-settings",
    JSON.stringify({
      providerMode: providerMode.value,
      compactMode: compactMode.checked,
      contextWindow: normalizedContextWindow(),
    })
  );
  localStorage.setItem("aios-profile", JSON.stringify({ name: profileName.value.trim(), role: profileRole.value.trim() }));
  localStorage.setItem(
    "aios-workspace",
    JSON.stringify({
      name: workspaceName.value.trim(),
      focus: workspaceFocus.value.trim(),
      runningTask: runningTask.value.trim(),
      activeFile: activeFile.value.trim(),
      activeTool: activeTool.value.trim(),
      terminalOutput: terminalOutput.value.trim(),
      browserResults: browserResults.value.trim(),
      mcpOutputs: mcpOutputs.value.trim(),
      developerInstructions: developerInstructions.value.trim(),
    })
  );
  document.body.classList.toggle("compact", compactMode.checked);
  if (persistSession) {
    syncSessionContext();
  }
}

async function syncSessionContext() {
  if (!activeSessionId) {
    return;
  }
  const workspace = loadJson("aios-workspace", {});
  try {
    const response = await authenticatedFetch("/api/v1/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: activeSessionId,
        active_project: workspace.name || "",
        current_workspace: {
          name: workspace.name || "",
          focus: workspace.focus || "",
        },
        running_task: workspace.runningTask || "",
        active_file: workspace.activeFile || "",
        open_files: splitOpenFiles(workspace.activeFile || ""),
        active_tool: workspace.activeTool || "",
        terminal_output: workspace.terminalOutput || "",
        browser_results: workspace.browserResults || "",
        mcp_outputs: workspace.mcpOutputs || "",
        developer_instructions: workspace.developerInstructions || "",
        user_preferences: {
          provider_mode: providerMode.value,
          compact_mode: compactMode.checked,
          context_window_tokens: normalizedContextWindow(),
        },
      }),
    });
    const payload = await response.json();
    if (payload.session && payload.session.id) {
      setActiveSession(payload.session.id);
    }
  } catch (error) {
    console.error("Could not sync session context", error);
  }
}

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || "null") || fallback;
  } catch {
    return fallback;
  }
}

function normalizedContextWindow() {
  const value = Number.parseInt(contextWindow.value, 10);
  if (Number.isNaN(value)) {
    return 4000;
  }
  return Math.max(500, Math.min(value, 128000));
}

function splitOpenFiles(value) {
  return String(value || "")
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function notify(title, detail) {
  const notices = loadJson("aios-notifications", []);
  notices.unshift({ title, detail, createdAt: new Date().toLocaleTimeString() });
  localStorage.setItem("aios-notifications", JSON.stringify(notices.slice(0, 8)));
  renderNotifications();
}

function renderNotifications() {
  const notices = loadJson("aios-notifications", []);
  notificationList.innerHTML = notices.length
    ? notices.map((item) => `<div class="notice"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.createdAt)} - ${escapeHtml(item.detail)}</small></div>`).join("")
    : '<div class="notice"><small>No notifications yet.</small></div>';
}

function setComposerBusy(isBusy) {
  if (fileInput) {
    fileInput.disabled = isBusy;
  }
}

function setResponseActive(isActive) {
  if (!sendMessageButton) {
    return;
  }

  sendMessageButton.classList.toggle("danger-action", isActive);
  sendMessageButton.classList.toggle("stop-action", isActive);
  sendMessageButton.setAttribute("aria-label", isActive ? "Stop response" : "Send message");
  sendMessageButton.textContent = isActive ? "■" : "↑";
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function recoverInterruptedStream() {
  const recoveryId = localStorage.getItem(ACTIVE_STREAM_KEY) || activeConversationId;
  if (!recoveryId) return;

  localStorage.removeItem(ACTIVE_STREAM_KEY);
  try {
    await openConversation(recoveryId);
    await loadConversations();
  } catch (error) {
    console.error("Could not recover interrupted stream", error);
  }
}

async function boot() {
  // A browser/page start should always present a clean composer. Persisted
  // conversations remain available in Recent and are only opened by the user.
  setActiveConversation(null);
  setActiveThread("main");
  localStorage.removeItem(ACTIVE_STREAM_KEY);
  messages.innerHTML = "";
  const authenticated = await ensureAuthenticated();
  if (!authenticated) return;
  await ensureSession();
  await syncSessionContext();
  await loadConversations();
  await loadArtifacts();
  renderNotifications();
  updateEmptyState();
  input.focus();
}

boot();
