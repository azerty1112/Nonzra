/* Background service worker: إدارة الإعدادات والرسائل بين البوبböb والمحتوى. */

const DEFAULT_API_BASE = "http://localhost:8000";

function broadcast(message) {
  chrome.tabs.query({}, (tabs) => {
    for (const tab of tabs) {
      if (tab.id !== undefined) {
        chrome.tabs.sendMessage(tab.id, message).catch(() => {});
      }
    }
  });
}

chrome.storage.onChanged.addListener((changes) => {
  if (changes.enabled) {
    broadcast({ type: "set_enabled", enabled: changes.enabled.newValue });
  }
  if (changes.autoMode) {
    broadcast({ type: "set_auto_mode", autoMode: changes.autoMode.newValue });
  }
  if (changes.apiBase) {
    broadcast({ type: "set_api_base", apiBase: changes.apiBase.newValue });
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "get_settings") {
    chrome.storage.local.get(
      { enabled: true, autoMode: true, apiBase: DEFAULT_API_BASE },
      (settings) => sendResponse(settings)
    );
    return true;
  }
  if (msg.type === "solve_now") {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]?.id) {
        chrome.tabs.sendMessage(tabs[0].id, { type: "solve_now" }).catch(() => {});
      }
    });
    sendResponse({ ok: true });
  }
  return true;
});
