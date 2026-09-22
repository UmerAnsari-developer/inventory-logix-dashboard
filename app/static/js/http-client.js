/* =============================================================================
   InventoryLogix — HttpClient.
   AbortController timeout + retry with exponential backoff.
   Exposed as window.httpClient singleton.
   ============================================================================= */
class HttpClient {
  constructor(defaultOptions = {}) {
    this.defaults = {
      timeout: 10000,
      retryDelay: 1000,
      ...defaultOptions,
    };
  }

  async request(url, options = {}) {
    const { timeout, retries, retryDelay, ...fetchOptions } = {
      ...this.defaults,
      ...options,
    };

    const method = (fetchOptions.method || 'GET').toUpperCase();
    const maxRetries = retries != null
      ? retries
      : (method === 'GET' || method === 'HEAD' ? 2 : 0);

    // Header policy: JSON Content-Type only when there's a JSON-able body
    // and the caller hasn't set one already (never override FormData).
    const hasBody = fetchOptions.body != null;
    const isFormData = typeof FormData !== 'undefined' && fetchOptions.body instanceof FormData;
    const headers = new Headers(fetchOptions.headers || {});
    if (hasBody && !isFormData && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    fetchOptions.headers = headers;

    let lastError;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      let timeoutId; // declared before try so finally can always clear it
      try {
        const controller = new AbortController();
        timeoutId = setTimeout(() => controller.abort(), timeout);

        const response = await fetch(url, {
          ...fetchOptions,
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        return response;
      } catch (error) {
        lastError = error;
        if (attempt === maxRetries) break;
        // Exponential backoff: base * 2^attempt
        await new Promise((resolve) =>
          setTimeout(resolve, retryDelay * Math.pow(2, attempt)),
        );
      } finally {
        clearTimeout(timeoutId);
      }
    }

    throw lastError;
  }

  get(url, options) {
    return this.request(url, { method: 'GET', ...options });
  }

  post(url, data, options) {
    return this.request(url, {
      method: 'POST',
      body: JSON.stringify(data),
      ...options,
    });
  }

  put(url, data, options) {
    return this.request(url, {
      method: 'PUT',
      body: JSON.stringify(data),
      ...options,
    });
  }

  delete(url, options) {
    return this.request(url, { method: 'DELETE', ...options });
  }
}

window.httpClient = new HttpClient();
