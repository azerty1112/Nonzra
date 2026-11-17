/* لوحة تحكم Nonzra - التفاعل مع API */

// عنوان نسبي: يعمل من نفس الأصل (سيرفر محلي أو عبر بروكسي/نفق) بدون تعديل
const API = window.NONECAP_API_BASE || "";
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
  const tb = document.getElementById("historyBody");
  if (!tb) return;
  tb.innerHTML = "";
  try {
    // النشاط الأخير من سجل التدقيق (أدق من التجميع)
    const d = await api("/analytics/recent-activity?limit=25");
    const events = d.recent_events || [];
    if (events.length) {
      events.forEach(ev => {
        const tr = document.createElement("tr");
        const details = ev.details || {};
        const type = details.captcha_type || ev.resource_id || "-";
        const ok = ev.success;
        const conf = typeof details.confidence === "number" ? (details.confidence * 100).toFixed(0) + "%" : "-";
        const ms = details.response_time_ms != null ? details.response_time_ms + "ms" : "-";
        tr.innerHTML = `
          <td>${new Date(ev.timestamp).toLocaleTimeString("ar-SA", { hour12: false })}</td>
          <td>${escapeHtml(String(type))}</td>
          <td>${escapeHtml(String(details.text || ev.resource || "-"))}</td>
          <td>${conf}</td>
          <td>${ms}</td>
          <td>${escapeHtml(details.strategy || ev.action || "-")}</td>
          <td><span class="badge ${ok ? "badge-ok" : "badge-bad"}">${ok ? "نجاح" : "فشل"}</span></td>`;
        tb.appendChild(tr);
      });
      return;
    }
  } catch (e) {
    // لا مفتاح API أو سجل فارغ → نعود للتجميع من /stats
  }
  try {
    const d = await api("/stats");
    const byType = d.by_type || {};
    Object.entries(byType).forEach(([type, count]) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${new Date().toLocaleDateString("ar-SA")}</td><td>${escapeHtml(type)}</td><td>${count}</td><td>-</td><td>-</td><td>-</td><td><span class="badge badge-ok">تم</span></td>`;
      tb.appendChild(tr);
    });
  } catch (e) {
    log("فشل تحميل التاريخ: " + e.message, "bad");
  }
}

async function loadCapabilities() {
  try {
    const d = await api("/capabilities");
    const types = d.supported_types || [];
    const el = document.getElementById("capTypes");
    if (el) el.textContent = types.length;
    const list = document.getElementById("capList");
    if (list) {
      list.innerHTML = types
        .map(t => `<span class="chip">${escapeHtml(t)}</span>`)
        .join("");
    }
    const sel = document.getElementById("captchaTypeSelect");
    if (sel && !sel.dataset.filled) {
      sel.innerHTML = `<option value="">كشف تلقائي</option>` +
        types.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join("");
      sel.dataset.filled = "1";
    }
  } catch (e) {
    log("فشل تحميل القدرات: " + e.message, "bad");
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
    log("تم إنشاء مفتاح API: " + (d.key_id || "").slice(0, 8), "ok");
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
  form.append("max_escalations", document.getElementById("maxEscalations")?.value || "2");

  const resEl = document.getElementById("autoResult");
  const btn = document.querySelector("button[onclick='solveAuto()']");
  if (btn) btn.disabled = true;
  resEl.style.display = "block";
  resEl.innerHTML = "جاري التحليل الذكي...";

  try {
    const d = await api("/auto", { method: "POST", body: form });
    const res = d.result || {};
    const confidence = typeof res.confidence === "number" ? res.confidence : 0;
    const detection = typeof d.detection_confidence === "number" ? d.detection_confidence : 0;
    const trace = Array.isArray(d.trace) ? d.trace : [];
    const alerts = Array.isArray(d.alerts) ? d.alerts : [];
    resEl.innerHTML = `
      <div class="result-head">
        <span class="badge ${res.success ? "badge-ok" : "badge-bad"}">${res.success ? "نجاح" : "فشل"}</span>
        <span style="color:var(--muted);font-size:.85rem">${escapeHtml(d.detected_type || "-")} · ثقة الكشف ${(detection*100).toFixed(1)}%</span>
      </div>
      <div class="result-text">${escapeHtml(res.text || res.token || "—")}</div>
      <div class="result-meta">
        <span>الثقة: ${(confidence*100).toFixed(1)}%</span>
        <span>الاستراتيجية: ${escapeHtml(d.strategy_used || "-")}</span>
        <span>التصعيدات: ${d.escalations ?? 0}</span>
        <span>الزمن: ${d.total_time_ms ?? res.response_time_ms ?? 0}ms</span>
      </div>
      ${alerts.length ? `<div class="result-alerts">${alerts.map(a => `<div>⚠ ${escapeHtml(a.message || a.type || "")}</div>`).join("")}</div>` : ""}
      <details style="margin-top:8px;font-size:.8rem;color:#94a3b8">
        <summary style="cursor:pointer">مسار القرار (${trace.length} خطوة)</summary>
        <div style="margin-top:6px">${trace.map(t => `<div>• ${escapeHtml(t)}</div>`).join("")}</div>
      </details>
    `;
    log("الحل التلقائي اكتمل: " + (d.result.success ? "نجاح" : "فشل"), d.result.success ? "ok" : "bad");
    loadStats();
    loadHistory();
    // Show experience stats
    try {
      const exp = await api("/self-improve/stats");
      document.getElementById("trainConfirmed").textContent = exp.dataset.confirmed || 0;
      document.getElementById("trainRate").textContent = (exp.dataset.confirmation_rate || 0) + "%";
    } catch (e) {
      // ignored
    }
  } catch (e) {
    resEl.innerHTML = "خطأ: " + escapeHtml(e.message);
    log("فشل الحل التلقائي: " + e.message, "bad");
  } finally {
    if (btn) btn.disabled = false;
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


function pct(x) { return Math.round((Number(x) || 0) * 100) + "%"; }

function meterClass(rate) {
  if (rate >= 0.75) return "";
  if (rate >= 0.55) return "violet";
  return "amber";
}

async function loadMind() {
  try {
    const d = await api("/mind");
    const rating = Number(d.self_rating || 0);
    document.getElementById("mindRating").textContent = pct(rating);
    document.getElementById("mindRating").style.color =
      rating >= 0.75 ? "var(--success)" : rating >= 0.55 ? "var(--accent)" : "var(--warning)";
    document.getElementById("mindMood").textContent = d.mood || "—";
    document.getElementById("mindCycles").textContent =
      `${d.cycles || 0} دورة تعلّم · نجاح حديث ${pct(d.recent_success_rate)}`;
    const brier = d.calibration && d.calibration.brier_score;
    document.getElementById("mindBrier").textContent =
      brier === null || brier === undefined ? "لا بيانات كافية بعد" : String(brier);

    const ranking = (d.skills && d.skills.ranking) || [];
    const skillsEl = document.getElementById("mindSkills");
    if (ranking.length) {
      skillsEl.innerHTML = ranking.map(sk => `
        <div class="skill-row">
          <span style="color:#cbd5e1">${escapeHtml(sk.captcha_type)}</span>
          <div class="meter ${meterClass(sk.posterior_mean)}"><i style="width:${Math.round(sk.posterior_mean * 100)}%"></i></div>
          <span class="stat-sub" style="text-align:left">${pct(sk.posterior_mean)}</span>
        </div>`).join("");
    } else {
      skillsEl.innerHTML = `<div class="stat-sub">لم أجرّب أي نوع بعد — أول حل سيبدأ التعلّم.</div>`;
    }

    const notes = d.notes || [];
    document.getElementById("mindNotes").innerHTML = notes
      .map(n => `<li>${escapeHtml(n)}</li>`).join("");

    const exp = d.next_experiment;
    document.getElementById("mindPlan").innerHTML = exp
      ? `<strong style="color:var(--accent)">تجربتي القادمة:</strong> ${escapeHtml(exp.target_type)} — ${escapeHtml(exp.advice)}`
      : `<span class="stat-sub">العقل راضٍ عن أدائه الحالي ولا يرى تجربة عاجلة.</span>`;
  } catch (e) {
    log("فشل تحميل حالة العقل: " + e.message, "warn");
  }
}

async function loadKnowledge() {
  const el = document.getElementById("knowledgeCards");
  el.innerHTML = `<div class="card-mini"><p>جاري التحميل...</p></div>`;
  try {
    const d = await api("/knowledge");
    const cards = (d.cards || []).slice(0, 12);
    if (!cards.length) {
      el.innerHTML = `<div class="card-mini"><p>لا توجد بطاقات.</p></div>`;
      return;
    }
    el.innerHTML = cards.map(c => `
      <div class="card-mini">
        <h4>${escapeHtml(c.title)} <span class="stat-sub">· صعوبة ${pct(c.difficulty)}</span></h4>
        <p>${escapeHtml(c.summary)}</p>
        ${c.facts && c.facts.length ? `<ul>${c.facts.slice(0, 3).map(f => `<li>${escapeHtml(f)}</li>`).join("")}</ul>` : ""}
      </div>`).join("");
  } catch (e) {
    el.innerHTML = `<div class="card-mini"><p>تعذّر تحميل البطاقات: ${escapeHtml(e.message)}</p></div>`;
  }
}

loadMind();
setInterval(loadMind, 15000);

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
loadCapabilities();
setInterval(loadCapabilities, 60000);
