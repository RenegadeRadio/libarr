/** Thin API client for the Libarr backend (dev-proxied via vite). */

async function api(path, options = {}) {
  const resp = await fetch(`/api/v1${path}`, options)
  if (!resp.ok) {
    throw new Error(`API ${resp.status}: ${await resp.text()}`)
  }
  return resp.json()
}

export default api
