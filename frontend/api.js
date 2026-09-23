export class ApiClientError extends Error {
  constructor(code, message, status, details) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.status = status;
    // ApiError.details are merged into the response `error` object by Core
    // (e.g. CORE_REFERENCE_SET_REQUIRED's `outfits`, CORE_REFERENCE_SETTINGS_MISMATCH's
    // `diff`). Keep them, minus the always-present code/message, for callers that need
    // structured data beyond the human-readable message.
    this.details = details && typeof details === "object" ? details : {};
  }
}

const codePattern = /^[A-Z][A-Z0-9_]{0,99}$/;

function serviceError(payload, status, token) {
  const error = payload && typeof payload.error === "object" ? payload.error : null;
  const code = error && typeof error.code === "string" && codePattern.test(error.code) &&
    (!token || !error.code.includes(token)) ? error.code : "CLIENT_HTTP_ERROR";
  const message = error && typeof error.message === "string" &&
    (!token || !error.message.includes(token)) ? error.message.slice(0, 500) : "Service request failed";
  const details = error ? { ...error } : {};
  delete details.code;
  delete details.message;
  return new ApiClientError(code, message, status, code === "CLIENT_HTTP_ERROR" ? {} : details);
}

export class ApiClient {
  constructor({ baseUrl = "", token = "", timeoutMs = 30000 } = {}) {
    const origin = window.location.origin;
    const resolved = new URL(baseUrl || origin, origin);
    if (resolved.origin !== origin || resolved.username || resolved.password ||
        (resolved.pathname !== "/" && resolved.pathname !== "" ) || resolved.search || resolved.hash) {
      throw new TypeError("baseUrl must be this page's origin");
    }
    if (typeof token !== "string" || /[\u0000-\u001f\u007f]/.test(token)) {
      throw new TypeError("token must be a single-line string");
    }
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
      throw new TypeError("timeoutMs must be positive");
    }
    this.baseUrl = origin;
    this.token = token;
    this.timeoutMs = timeoutMs;
  }

  #path(path) {
    const pathname = typeof path === "string" ? path.split(/[?#]/, 1)[0] : "";
    if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//") || path.includes("\\") || path.includes("#") ||
        pathname.split("/").slice(1).some((part) => part === "." || part === "..")) {
      throw new ApiClientError("CLIENT_INVALID_PATH", "Request path must be same-origin", 400);
    }
    const resolved = new URL(path, this.baseUrl);
    if (resolved.origin !== this.baseUrl || !resolved.pathname.startsWith("/")) {
      throw new ApiClientError("CLIENT_INVALID_PATH", "Request path must be same-origin", 400);
    }
    return resolved.pathname + resolved.search;
  }

  async request(method, path, body, key) {
    const headers = { Accept: "application/json" };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    if (key !== undefined) {
      if (typeof key !== "string" || key.length < 1 || key.length > 200 || /[\u0000-\u001f\u007f]/.test(key)) {
        throw new ApiClientError("CLIENT_INVALID_IDEMPOTENCY_KEY", "Idempotency key must be 1..200 characters", 400);
      }
      headers["Idempotency-Key"] = key;
    }
    const options = { method, headers, redirect: "error" };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      try { options.body = JSON.stringify(body); }
      catch (_) { throw new ApiClientError("CLIENT_INVALID_BODY", "Request body must be JSON serializable", 400); }
    }
    const localPath = this.#path(path);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let response;
    try {
      try { response = await fetch(localPath, {...options, signal: controller.signal}); }
      catch (_) {
        if (controller.signal.aborted) throw new ApiClientError("CLIENT_TIMEOUT", "Service request timed out", 504);
        throw new ApiClientError("CLIENT_TRANSPORT_ERROR", "Service transport failed", 503);
      }
      let payload;
      try { payload = await response.json(); }
      catch (_) {
        if (controller.signal.aborted) throw new ApiClientError("CLIENT_TIMEOUT", "Service request timed out", 504);
        throw new ApiClientError("CLIENT_PROTOCOL_ERROR", "Service returned invalid JSON", 502);
      }
      if (!response.ok) throw serviceError(payload, response.status, this.token);
      if (!payload || typeof payload !== "object") throw new ApiClientError("CLIENT_PROTOCOL_ERROR", "Service returned an invalid JSON payload", 502);
      return payload;
    } finally {
      clearTimeout(timer);
    }
  }

  get(path) { return this.request("GET", path); }
  post(path, body = {}, key) { return this.request("POST", path, body, key); }
  patch(path, body) { return this.request("PATCH", path, body); }
  put(path, body) { return this.request("PUT", path, body); }

  async imageBlob(path) {
    const headers = this.token ? { Authorization: `Bearer ${this.token}` } : {};
    const localPath = this.#path(path);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let response;
    try {
      try { response = await fetch(localPath, { method: "GET", headers, redirect: "error", signal: controller.signal }); }
      catch (_) {
        if (controller.signal.aborted) throw new ApiClientError("CLIENT_TIMEOUT", "Service request timed out", 504);
        throw new ApiClientError("CLIENT_TRANSPORT_ERROR", "Service transport failed", 503);
      }
      if (!response.ok) {
        let payload = null;
        try { payload = await response.json(); }
        catch (_) {
          if (controller.signal.aborted) throw new ApiClientError("CLIENT_TIMEOUT", "Service request timed out", 504);
          /* Binary endpoint errors need not be JSON. */
        }
        throw serviceError(payload, response.status, this.token);
      }
      try { return await response.blob(); }
      catch (_) {
        if (controller.signal.aborted) throw new ApiClientError("CLIENT_TIMEOUT", "Service request timed out", 504);
        throw new ApiClientError("CLIENT_PROTOCOL_ERROR", "Service returned invalid binary data", 502);
      }
    } finally {
      clearTimeout(timer);
    }
  }
}
