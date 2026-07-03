// Thin API client. Uses same-origin paths; Vite proxies them to the backend
// in dev (see vite.config.js).

export async function fetchResearch(ticker) {
  const res = await fetch(`/research/${encodeURIComponent(ticker)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }

  return res.json();
}
