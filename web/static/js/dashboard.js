/* لوحة تحكم Nonzra - التفاعل مع API */

const API = "http://localhost:8000";
let ws = null;
let logTimer = null;

function log(msg, type = "info") {
  const el = document.getElementById("logs");
  if (!el) return;
  const line = document.createElement("div");
  line.className = "log-line " + (type === "ok" ? "ok" : type === "bad" ? "bad" : type === "warn" ? "warn" : "");
  const t = new Date().toLocaleTimeString("ar-SA", { hour12: false });
  line.innerHTML = `<span style="color:#94a3b8">[${t}]</span> <span>${escapeHtml(msg)}</span>`;
  el.prepend(line);
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

async function api(path, opts = {}) {
  const headers = { "Accept": "application/json", ...(opts.headers || {}) };
  const res = await fetch(API + path, { ...opts, headers });
  if (res.status === 401) throw new Error("غير مصرح");
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(txt || res.status);
  }
  return res.json();
}

async function checkStatus() {
  try {
    const d = await api("/health");
    document.getElementById("statusText").textContent = "السيرفر يعمل";
    document.getElementById("statusDot").className = "dot ok";
    log("الاتصال بالسيرفر ناجح", "ok");
  } catch (e) {
    document.getElementById("statusText").textContent = "السيرفر غير متاح";
    document.getElementById("statusDot").className = "dot";
    log("تعذر الاتصال بالسيرفر: " + e.message, "bad");
  }
}

async function loadStats() {
  try {
    const d = await api("/stats");
    document.getElementById("statTotal").textContent = d.total || 0;
    document.getElementById("statRate").textContent = (d.success_rate || 0) + "%";
    document.getElementById("statAvg").textContent = (d.avg_response_time_ms || 0) + "ms";
  } catch (e) {
    log("فشل تحميل الإحصائيات: " + e.message, "bad");
  }
}

async function loadAutoStatus() {
  try {
    const d = await api("/auto/status");
    const w = d.worker || {};
    document.getElementById("statWorker").textContent = w.running ? "يعمل" : "متوقف";
    document.getElementById("statWorker").style.color = w.running ? "var(--success)" : "var(--danger)";
    loadTrainingStats();
  } catch (e) {
    log("فشل تحميل حالة العامل: " + e.message, "bad");
  }
}

async function loadHistory() {
  try {
    const d = await api("/stats");
    const tb = document.getElementById("historyBody");
    tb.innerHTML = "";
    const byType = d.by_type || {};
    Object.entries(byType).forEach(([type, count]) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${new Date().toLocaleDateString("ar-SA")}</td><td>${type}</td><td>${count}</td><td>-</td><td>-</td><td>-</td><td><span class="badge badge-ok">تم</span></td>`;
      tb.appendChild(tr);
    });
  } catch (e) {
    log("فشل تحميل التاريخ: " + e.message, "bad");
  }
}

async function loadKeys() {
  try {
    const keys = await api("/api/keys");
    const tb = document.getElementById("keysBody");
    tb.innerHTML = "";
    (keys || []).forEach(k => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code style="color:#38bdf8">${k.key_id.slice(0,8)}...</code></td>
        <td>${k.name || "-"}</td>
        <td><span class="badge ${k.is_active ? "badge-ok" : "badge-bad"}">${k.is_active ? "فعال" : "موقف"}</span></td>
        <td>${k.usage_count || 0}</td>
        <td><button class="btn btn-danger btn-sm" onclick="deleteKey('${k.key_id}')">إلغاء</button></td>
      `;
      tb.appendChild(tr);
    });
  } catch (e) {
    log("فشل تحميل المفاتيح: " + e.message, "bad");
  }
}

async function createKey() {
  const name = document.getElementById("keyName").value || null;
  try {
    const d = await api("/api/keys", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({ name }) });
    document.getElementById("keyResult").style.display = "block";
    document.getElementById("keyResult").textContent = "مفتاحك: " + d.api_key + "\n(احفظه، لن يُDisplayed مرة أخرى)";
    closeKeyModal();
    loadKeys();
    log("تم إنشاء مفتاح API: " + d.key_id.slice(0, 8), "ok");
  } catch (e) {
    alert("فشل إنشاء المفتاح: " + e.message);
  }
}

async function deleteKey(id) {
  if (!confirm("تأكيد إلغاء المفتاح؟")) return;
  try {
    await api("/api/keys/" + id, { method: "DELETE" });
    loadKeys();
    log("تم إلغاء المفتاح: " + id.slice(0, 8), "ok");
  } catch (e) {
    alert("فشل الإلغاء: " + e.message);
  }
}

function openKeyModal() { document.getElementById("keyModal").classList.add("show"); }
function closeKeyModal() { document.getElementById("keyModal").classList.remove("show"); }

async function solveAuto() {
  const fileInput = document.getElementById("captchaFile");
  if (!fileInput.files.length) { alert("يرجى اختيار ملف صورة"); return; }
  const form = new FormData();
  form.append("file", fileInput.files[0]);
  const type = document.getElementById("captchaType").value;
  if (type) form.append("captcha_type", type);
  const url = document.getElementById("captchaUrl").value;
  if (url) form.append("url", url);
  const sitekey = document.getElementById("captchaSitekey").value;
  if (sitekey) form.append("sitekey", sitekey);
  form.append("human_like", document.getElementById("humanLike").checked);
  form.append("max_escalations", "2");

  const resEl = document.getElementById("autoResult");
  resEl.style.display = "block";
  resEl.innerHTML = "جاري الحل التلقائي...";

  try {
    const d = await api("/auto", { method: "POST", body: form });
    resEl.innerHTML = `
      <div><strong>النوع المكتشف:</strong> ${d.detected_type} (ثقة ${(d.detection_confidence*100).toFixed(1)}%)</div>
      <div><strong>النتيجة:</strong> ${d.result.success ? "نجاح" : "فشل"}</div>
      <div><strong>النص/التوكن:</strong> ${d.result.text || d.result.token || "-"}</div>
      <div><strong>الثقة:</strong> ${(d.result.confidence*100).toFixed(1)}%</div>
      <div><strong>الاستراتيجية:</strong> ${d.strategy_used}</div>
      <div><strong>التصعيدات:</strong> ${d.escalations}</div>
      <div style="margin-top:8px;font-size:.8rem;color:#94a3b8">الت Trace: ${d.trace.join(" | ")}</div>
    `;
    log("الحل التلقائي اكتمل: " + (d.result.success ? "نجاح" : "فشل"), d.result.success ? "ok" : "bad");
    loadStats();
    loadHistory();
  } catch (e) {
    resEl.innerHTML = "خطأ: " + escapeHtml(e.message);
    log("فشل الحل التلقائي: " + e.message, "bad");
  }
}

async function startWorker() {
  try {
    await api("/auto/status");
    log("العامل الذكي يعمل بالفعل", "ok");
  } catch (e) {
    log("العامل غير متاح", "bad");
  }
}

async function loadTrainingStats() {
  try {
    const d = await api("/self-improve/stats");
    document.getElementById("trainConfirmed").textContent = d.dataset.confirmed || 0;
    document.getElementById("trainRate").textContent = (d.dataset.confirmation_rate || 0) + "%";
    document.getElementById("trainThreshold").textContent = d.threshold || 0.9;
  } catch (e) {
    // training endpoint قد لا يكون مفعّلاً بعد
  }
}

async function retrainModel() {
  try {
    const d = await api("/self-improve/retrain", { method: "POST" });
    const el = document.getElementById("trainResult");
    el.style.display = "block";
    el.innerHTML = `<div>إعادة التدريب: ${d.retrained ? "تم" : "لم يتم"}</div><div>${d.reason || ""}</div>`;
    log("إعادة التدريب: " + (d.retrained ? "تم" : "تخطٍ: " + (d.reason || "")), d.retrained ? "ok" : "warn");
    loadTrainingStats();
  } catch (e) {
    alert("فشل إعادة التدريب: " + e.message);
  }
}

function clearLogs() { document.getElementById("logs").innerHTML = ""; }

// تحديث دوري
setInterval(loadStats, 5000);
setInterval(loadAutoStatus, 5000);
setInterval(loadHistory, 10000);

// تشغيل أولي
checkStatus();
loadStats();
loadAutoStatus();
loadHistory();
loadKeys();
