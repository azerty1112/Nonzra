/* POPUP: إدارة الإضافة والاتصال بالسيرفر المحلي. */

const API_DEFAULT = "http://localhost:8000";
const enabledEl = document.getElementById("enabled");
const autoModeEl = document.getElementById("autoMode");
const apiBaseEl = document.getElementById("apiBase");
const solveBtn = document.getElementById("solveBtn");
const statusEl = document.getElementById("status");

function setStatus(text, kind = "") {
  statusEl.textContent = text;
  statusEl.className = "status " + kind;
}

chrome.storage.local.get({ enabled: true, autoMode: true, apiBase: API_DEFAULT }, (settings) => {
  enabledEl.checked = settings.enabled;
  autoModeEl.checked = settings.autoMode;
  apiBaseEl.value = settings.apiBase || API_DEFAULT;
  setStatus(settings.enabled ? "مفعل" : "معطل", settings.enabled ? "ok" : "");
});

enabledEl.addEventListener("change", () => {
  chrome.storage.local.set({ enabled: enabledEl.checked });
  setStatus(enabledEl.checked ? "مفعل" : "معطل", enabledEl.checked ? "ok" : "");
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) {
      chrome.tabs.sendMessage(tabs[0].id, { type: "set_enabled", enabled: enabledEl.checked }).catch(() => {});
    }
  });
});

autoModeEl.addEventListener("change", () => {
  chrome.storage.local.set({ autoMode: autoModeEl.checked });
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) {
      chrome.tabs.sendMessage(tabs[0].id, { type: "set_auto_mode", autoMode: autoModeEl.checked }).catch(() => {});
    }
  });
});

apiBaseEl.addEventListener("change", () => {
  chrome.storage.local.set({ apiBase: apiBaseEl.value });
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) {
      chrome.tabs.sendMessage(tabs[0].id, { type: "set_api_base", apiBase: apiBaseEl.value }).catch(() => {});
    }
  });
});

solveBtn.addEventListener("click", async () => {
  setStatus("جاري الحل...", "");
  try {
    const resp = await fetch(`${apiBaseEl.value || API_DEFAULT}/health`, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) throw new Error("السيرفر غير مستجيب");
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]?.id) {
        chrome.tabs.sendMessage(tabs[0].id, { type: "solve_now" }).catch(() => {});
      }
    });
    setStatus("تم إرسال أمر الحل", "ok");
  } catch (e) {
    setStatus("خطأ: " + e.message, "err");
  }
});
