/* Content script: يكشف عن تحديات الكبتشا وي sendها للسيرفر المحلي للحل التلقائي. */

const API_BASE_DEFAULT = "http://localhost:8000";
let API_BASE = API_BASE_DEFAULT;
let autoMode = true;
const SELECTORS = {
  hcaptchaIframe: 'iframe[src*="hcaptcha"]',
  hcaptchaCheckbox: '.h-captcha, .h-captcha-checkbox, [data-hcaptcha]',
  recaptcha: '.g-recaptcha, .g-recaptcha-badge',
  turnstile: '.cf-turnstile, [data-sitekey][data-callback]',
  imageCaptcha: 'img[src*="captcha"], img[alt*="captcha"], img[class*="captcha"]',
  drag: '.drag-captcha, .slider-captcha, [class*="drag"]',
  point: '.point-captcha, [class*="point"]',
};

let enabled = true;
let lastSolveTime = 0;
const COOLDOWN_MS = 4000;

try {
  chrome.storage.local.get(
    { enabled: true, autoMode: true, apiBase: API_BASE_DEFAULT },
    (s) => {
      enabled = !!s.enabled;
      autoMode = !!s.autoMode;
      API_BASE = (s.apiBase || API_BASE_DEFAULT).replace(/\/$/, "");
    }
  );
} catch {
  /* خارج سياق الإضافة */
}

async function fetchWithTimeout(url, init, ms = 20000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(id);
  }
}

async function solveImageFile(file) {
  const form = new FormData();
  form.append("file", file, "captcha.png");
  let endpoint;
  if (autoMode) {
    endpoint = `${API_BASE}/auto`;
    form.append("human_like", "true");
    form.append("max_escalations", "2");
  } else {
    endpoint = `${API_BASE}/solve/image`;
    form.append("psm", "7");
    form.append("preprocess", "true");
    form.append("resize_width", "400");
  }
  const resp = await fetchWithTimeout(
    endpoint,
    { method: "POST", body: form },
    autoMode ? 45000 : 20000
  );
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const body = await resp.json();
  if (autoMode && body.result) {
    return {
      ...body.result,
      detected_type: body.detected_type,
      detection_confidence: body.detection_confidence,
      strategy_used: body.strategy_used,
      escalations: body.escalations,
      trace: body.trace,
    };
  }
  return body.result ? body.result : body;
}

async function solveImageSrc(src) {
  try {
    const resp = await fetchWithTimeout(src);
    const blob = await resp.blob();
    return solveImageFile(blob);
  } catch (e) {
    return { success: false, error: e.message };
  }
}

async function solveDrag(imageSrc, templateSrc) {
  const form = new FormData();
  const [imgBlob, tmplBlob] = await Promise.all([fetchBlob(imageSrc), fetchBlob(templateSrc)]);
  if (!imgBlob || !tmplBlob) return { success: false, error: "فشل تحميل الصور" };
  form.append("file", imgBlob, "captcha.png");
  form.append("template", tmplBlob, "template.png");
  const resp = await fetchWithTimeout(`${API_BASE}/solve/drag`, { method: "POST", body: form });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function solvePoint(imageSrc, targetColor) {
  const form = new FormData();
  const blob = await fetchBlob(imageSrc);
  if (!blob) return { success: false, error: "فشل تحميل الصورة" };
  form.append("file", blob, "captcha.png");
  if (targetColor) form.append("target_color", targetColor);
  form.append("min_area", "20");
  const resp = await fetchWithTimeout(`${API_BASE}/solve/point`, { method: "POST", body: form });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function fetchBlob(url) {
  try {
    const r = await fetchWithTimeout(url);
    return await r.blob();
  } catch { return null; }
}

function findCaptchaImages() {
  const imgs = Array.from(document.querySelectorAll(SELECTORS.imageCaptcha));
  return imgs.filter((img) => {
    const r = img.getBoundingClientRect();
    return r.width > 20 && r.height > 20 && (img.src || img.currentSrc);
  });
}

async function trySolve() {
  if (!enabled) return;
  const now = Date.now();
  if (now - lastSolveTime < COOLDOWN_MS) return;

  const imgs = findCaptchaImages();
  for (const img of imgs) {
    const src = img.src || img.currentSrc;
    if (!src) continue;
    try {
      const result = await solveImageSrc(src);
      if (result.success && result.text) {
        lastSolveTime = now;
        document.dispatchEvent(new CustomEvent("nonecap:solved", {
          detail: {
            type: result.detected_type || "image",
            text: result.text,
            element: img,
            strategy: result.strategy_used,
            escalations: result.escalations,
          },
        }));
        const input = img.closest("form")?.querySelector('input[type="text"]');
        if (input) {
          input.value = result.text;
          input.dispatchEvent(new Event("input", { bubbles: true }));
          input.dispatchEvent(new Event("change", { bubbles: true }));
        }
        return;
      }
    } catch (e) {
      continue;
    }
  }
}

const observer = new MutationObserver(() => {
  trySolve();
});
observer.observe(document.documentElement, { childList: true, subtree: true });

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "set_enabled") {
    enabled = !!msg.enabled;
  } else if (msg.type === "set_auto_mode") {
    autoMode = !!msg.autoMode;
  } else if (msg.type === "set_api_base") {
    API_BASE = (msg.apiBase || API_BASE_DEFAULT).replace(/\/$/, "");
  } else if (msg.type === "solve_now") {
    trySolve();
  }
});

document.addEventListener("DOMContentLoaded", () => {
  trySolve();
});
