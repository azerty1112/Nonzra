// عميل تايبسكريبت لسيرفر NoneCap Clone (Node.js, Bun, Deno, متصفح)

export interface SolveResult {
  success: boolean;
  captcha_type: string;
  text?: string | null;
  token?: string | null;
  confidence: number;
  response_time_ms: number;
  error?: string | null;
  metadata: Record<string, unknown>;
}

export interface AutoSolveResult {
  result: SolveResult;
  detected_type: string;
  detection_confidence: number;
  strategy_used: string;
  params_used: Record<string, unknown>;
  escalations: number;
  trace: string[];
  alerts: Record<string, unknown>[];
  total_time_ms: number;
}

export interface AutoSolveOptions extends BaseSolveOptions {
  human_like?: boolean;
  max_escalations?: number;
}

export interface BaseSolveOptions {
  sitekey?: string;
  url?: string;
  action?: string;
  cdata?: string;
  target_color?: string;
  min_area?: number;
  psm?: number;
  oem?: number;
  whitelist?: string;
  preprocess?: boolean;
  resize_width?: number;
  threshold?: string;
}

export interface NoneCapOptions {
  baseUrl?: string;
  timeout?: number;
  apiKey?: string;
  fetch?: typeof fetch;
}

export class NoneCap {
  private baseUrl: string;
  private timeout: number;
  private apiKey?: string;
  private fetchFn: typeof fetch;

  constructor(options: NoneCapOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "http://localhost:8000").replace(/\/$/, "");
    this.timeout = options.timeout ?? 60000;
    this.apiKey = options.apiKey;
    this.fetchFn = options.fetch ?? (globalThis.fetch as typeof fetch);
  }

  private headers(): HeadersInit {
    const h: HeadersInit = { Accept: "application/json" };
    if (this.apiKey) {
      (h as Record<string, string>)["Authorization"] = `Bearer ${this.apiKey}`;
    }
    return h;
  }

  private async request(path: string, init: RequestInit): Promise<Response> {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), this.timeout);
    try {
      return await this.fetchFn(`${this.baseUrl}${path}`, {
        ...init,
        headers: { ...this.headers(), ...(init.headers || {}) },
        signal: controller.signal,
      });
    } finally {
      clearTimeout(id);
    }
  }

  private async parseResult(resp: Response): Promise<SolveResult> {
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`NoneCap error ${resp.status}: ${text}`);
    }
    const body = (await resp.json()) as any;
    return body.result ?? body;
  }

  async solve(
    captchaType: string,
    options: BaseSolveOptions = {},
    file?: File | Blob,
    templateFile?: File | Blob
  ): Promise<SolveResult> {
    const formData = new FormData();
    formData.append("captcha_type", captchaType);
    if (options.sitekey) formData.append("sitekey", options.sitekey);
    if (options.url) formData.append("url", options.url);
    if (options.action) formData.append("action", options.action);
    if (options.cdata) formData.append("cdata", options.cdata);
    if (options.target_color) formData.append("target_color", options.target_color);
    if (options.min_area !== undefined) formData.append("min_area", String(options.min_area));
    if (options.psm !== undefined) formData.append("psm", String(options.psm));
    if (options.oem !== undefined) formData.append("oem", String(options.oem));
    if (options.whitelist) formData.append("whitelist", options.whitelist);
    formData.append("preprocess", String(options.preprocess ?? true));
    if (options.resize_width !== undefined) formData.append("resize_width", String(options.resize_width));
    if (options.threshold) formData.append("threshold", options.threshold);
    if (file) formData.append("file", file, "captcha.png");
    if (templateFile) formData.append("template", templateFile, "template.png");

    const resp = await this.request(`/solve/${captchaType}`, { method: "POST", body: formData });
    return this.parseResult(resp);
  }

  async solveImage(file: File | Blob, options: BaseSolveOptions = {}): Promise<SolveResult> {
    return this.solve("image", options, file);
  }

  async solveImageB64(imageB64: string, options: BaseSolveOptions = {}): Promise<SolveResult> {
    const payload: Record<string, unknown> = { image_b64: imageB64, ...options };
    const resp = await this.request("/solve/image/b64", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return this.parseResult(resp);
  }

  async solveHCaptcha(
    sitekey: string,
    url: string,
    imageB64?: string
  ): Promise<SolveResult> {
    const payload: Record<string, unknown> = { sitekey, url };
    if (imageB64) payload.image_b64 = imageB64;
    const resp = await this.request("/solve/hcaptcha", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return this.parseResult(resp);
  }

  async solveReCaptcha(
    sitekey: string,
    url: string,
    captchaType: string = "recaptcha_v2",
    action?: string,
    imageB64?: string
  ): Promise<SolveResult> {
    const payload: Record<string, unknown> = { captcha_type: captchaType, sitekey, url };
    if (action) payload.action = action;
    if (imageB64) payload.image_b64 = imageB64;
    const resp = await this.request(`/solve/${captchaType}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return this.parseResult(resp);
  }

  async solveTurnstile(
    sitekey: string,
    url: string,
    action?: string,
    cdata?: string
  ): Promise<SolveResult> {
    const payload: Record<string, unknown> = { sitekey, url };
    if (action) payload.action = action;
    if (cdata) payload.cdata = cdata;
    const resp = await this.request("/solve/turnstile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return this.parseResult(resp);
  }

  async solveDrag(file: File | Blob, templateFile?: File | Blob): Promise<SolveResult> {
    return this.solve("drag", {}, file, templateFile);
  }

  async solvePoint(
    file: File | Blob,
    options: BaseSolveOptions = {}
  ): Promise<SolveResult> {
    return this.solve("point", options, file);
  }

  async solveAsyncSubmit(
    captchaType: string,
    options: BaseSolveOptions = {},
    file?: File | Blob
  ): Promise<string> {
    const formData = new FormData();
    formData.append("captcha_type", captchaType);
    if (options.sitekey) formData.append("sitekey", options.sitekey);
    if (options.url) formData.append("url", options.url);
    for (const [k, v] of Object.entries(options)) {
      if (v !== undefined && v !== null) formData.append(k, String(v));
    }
    if (file) formData.append("file", file, "captcha.png");
    const resp = await this.request(`/solve/async/${captchaType}`, { method: "POST", body: formData });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`NoneCap error ${resp.status}: ${text}`);
    }
    const body = await resp.json();
    return body.job_id ?? "";
  }

  async jobStatus(jobId: string): Promise<SolveResult> {
    const resp = await this.request(`/job/${jobId}`, { method: "GET" });
    return this.parseResult(resp);
  }

  async subscribeJob(jobId: string, onUpdate: (result: SolveResult) => void): Promise<void> {
    const ws = new WebSocket(`${this.baseUrl.replace(/^http/, "ws")}/ws/job/${jobId}`);
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.result) onUpdate(data.result);
      } catch {}
    };
  }

  async auto(
    options: AutoSolveOptions = {},
    file?: File | Blob,
    templateFile?: File | Blob
  ): Promise<AutoSolveResult> {
    const formData = new FormData();
    if (options.sitekey) formData.append("sitekey", options.sitekey);
    if (options.url) formData.append("url", options.url);
    if (options.action) formData.append("action", options.action);
    if (options.cdata) formData.append("cdata", options.cdata);
    formData.append("human_like", String(options.human_like ?? false));
    formData.append("max_escalations", String(options.max_escalations ?? 2));
    if (file) formData.append("file", file, "captcha.png");
    if (templateFile) formData.append("template", templateFile, "template.png");
    const resp = await this.request("/auto", { method: "POST", body: formData });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`NoneCap error ${resp.status}: ${text}`);
    }
    return (await resp.json()) as AutoSolveResult;
  }

  async autoSubmit(
    options: AutoSolveOptions = {},
    file?: File | Blob,
    templateFile?: File | Blob
  ): Promise<string> {
    const formData = new FormData();
    if (options.sitekey) formData.append("sitekey", options.sitekey);
    if (options.url) formData.append("url", options.url);
    formData.append("human_like", String(options.human_like ?? false));
    formData.append("max_escalations", String(options.max_escalations ?? 2));
    if (file) formData.append("file", file, "captcha.png");
    if (templateFile) formData.append("template", templateFile, "template.png");
    const resp = await this.request("/auto/async", { method: "POST", body: formData });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`NoneCap error ${resp.status}: ${text}`);
    }
    const body = await resp.json();
    return body.job_id ?? "";
  }

  async autoJobStatus(jobId: string): Promise<Record<string, unknown>> {
    const resp = await this.request(`/auto/job/${jobId}`, { method: "GET" });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`NoneCap error ${resp.status}: ${text}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  async autoStatus(): Promise<Record<string, unknown>> {
    const resp = await this.request("/auto/status", { method: "GET" });
    if (!resp.ok) throw new Error(`Auto status failed ${resp.status}`);
    return (await resp.json()) as Record<string, unknown>;
  }

  async feedback(
    strategy: string,
    success: boolean,
    options: {
      confidence?: number;
      response_time_ms?: number;
      captcha_type?: string;
      params?: Record<string, unknown>;
    } = {}
  ): Promise<Record<string, unknown>> {
    const payload: Record<string, unknown> = {
      strategy,
      success,
      confidence: options.confidence ?? 0,
      response_time_ms: options.response_time_ms ?? 0,
      captcha_type: options.captcha_type ?? "image",
    };
    if (options.params) payload.params = options.params;
    const resp = await this.request("/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`NoneCap error ${resp.status}: ${text}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  async createApiKey(options: { name?: string } = {}): Promise<Record<string, unknown>> {
    const resp = await this.request("/api/keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options),
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`NoneCap error ${resp.status}: ${text}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  async listApiKeys(): Promise<Record<string, unknown>[]> {
    const resp = await this.request("/api/keys", { method: "GET" });
    if (!resp.ok) throw new Error(`List keys failed ${resp.status}`);
    return (await resp.json()) as Record<string, unknown>[];
  }

  async deleteApiKey(keyId: string): Promise<Record<string, unknown>> {
    const resp = await this.request(`/api/keys/${keyId}`, { method: "DELETE" });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`NoneCap error ${resp.status}: ${text}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  async bulkAuto(
    items: Array<Record<string, unknown>>,
    callbackUrl?: string
  ): Promise<Record<string, unknown>> {
    const payload: Record<string, unknown> = { items };
    if (callbackUrl) payload.callbackUrl = callbackUrl;
    const resp = await this.request("/bulk/auto", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`NoneCap error ${resp.status}: ${text}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  async bulkStatus(bulkId: string): Promise<Record<string, unknown>> {
    const resp = await this.request(`/bulk/${bulkId}`, { method: "GET" });
    if (!resp.ok) throw new Error(`Bulk status failed ${resp.status}`);
    return (await resp.json()) as Record<string, unknown>;
  }

  async selfImproveStats(): Promise<Record<string, unknown>> {
    const resp = await this.request("/self-improve/stats", { method: "GET" });
    if (!resp.ok) throw new Error(`Self improve stats failed ${resp.status}`);
    return (await resp.json()) as Record<string, unknown>;
  }

  async selfImproveConfirm(sampleId: string, text?: string): Promise<Record<string, unknown>> {
    const resp = await this.request(`/self-improve/confirm/${sampleId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(text ? { text } : {}),
    });
    if (!resp.ok) {
      const textErr = await resp.text().catch(() => "");
      throw new Error(`NoneCap error ${resp.status}: ${textErr}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  async selfImproveRetrain(): Promise<Record<string, unknown>> {
    const resp = await this.request("/self-improve/retrain", { method: "POST" });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`NoneCap error ${resp.status}: ${text}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  async solveUrl(
    url: string,
    options?: {
      captchaType?: string;
      sitekey?: string;
      pageUrl?: string;
      humanLike?: boolean;
      maxEscalations?: number;
    }
  ): Promise<Record<string, unknown>> {
    const payload: Record<string, unknown> = { url };
    if (options?.captchaType) payload.captcha_type = options.captchaType;
    if (options?.sitekey) payload.sitekey = options.sitekey;
    if (options?.pageUrl) payload.page_url = options.pageUrl;
    if (options?.humanLike !== undefined) payload.human_like = options.humanLike;
    if (options?.maxEscalations !== undefined) payload.max_escalations = options.maxEscalations;
    const resp = await this.request("/solve/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`NoneCap error ${resp.status}: ${text}`);
    }
    return (await resp.json()) as Record<string, unknown>;
  }

  async health(): Promise<Record<string, unknown>> {
    const resp = await this.request("/health", { method: "GET" });
    if (!resp.ok) throw new Error(`Health check failed ${resp.status}`);
    return (await resp.json()) as Record<string, unknown>;
  }

  async stats(): Promise<Record<string, unknown>> {
    const resp = await this.request("/stats", { method: "GET" });
    if (!resp.ok) throw new Error(`Stats failed ${resp.status}`);
    return (await resp.json()) as Record<string, unknown>;
  }
}

export default NoneCap;
