/**
 * UI smoke test: drives the real Vue app in headless Chromium over CDP.
 * Exercises the full first-run flow: bootstrap → login → library grid → genre search.
 *
 * Prereqs: backend on :8787 with a migrated DB, vite dev on :5173.
 * Usage:   node scripts/ui-smoke.mjs
 */

import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const chrome = spawn(
  'chromium',
  [
    '--headless=new', '--no-sandbox', '--disable-gpu',
    '--remote-debugging-port=9222', '--window-size=1400,900', 'about:blank',
  ],
  { stdio: 'ignore' },
)

async function getTarget() {
  for (let i = 0; i < 40; i++) {
    try {
      const res = await fetch('http://127.0.0.1:9222/json')
      const targets = await res.json()
      const page = targets.find((t) => t.type === 'page')
      if (page) return page
    } catch { /* chrome still starting */ }
    await sleep(500)
  }
  throw new Error('no CDP target')
}

let msgId = 0
const pending = new Map()
function cdp(ws, method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++msgId
    pending.set(id, { resolve, reject })
    ws.send(JSON.stringify({ id, method, params }))
  })
}

const target = await getTarget()
const ws = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((r) => (ws.onopen = r))
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data)
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id).resolve(msg.result)
    pending.delete(msg.id)
  }
}

const evalJs = async (expr) => {
  const r = await cdp(ws, 'Runtime.evaluate', {
    expression: expr, awaitPromise: true, returnByValue: true,
  })
  return r?.result?.value
}

await cdp(ws, 'Page.enable')
await cdp(ws, 'Page.navigate', { url: 'http://localhost:5173/' })
await sleep(3500)

console.log('PAGE:', await evalJs('location.href'))
console.log('BODY:', (await evalJs('document.body.innerText'))?.slice(0, 300))

// First-run: create admin, which also logs in.
await evalJs(`(() => {
  const inputs = document.querySelectorAll('input')
  inputs[0].value = 'admin'; inputs[0].dispatchEvent(new Event('input', { bubbles: true }))
  inputs[1].value = 'hunter2!'; inputs[1].dispatchEvent(new Event('input', { bubbles: true }))
  return true
})()`)
await evalJs(`document.querySelector('button').click()`)
await sleep(4500)
console.log('AFTER LOGIN URL:', await evalJs('location.href'))
const libraryText = (await evalJs('document.body.innerText')) || ''
console.log('LIBRARY GRID:', libraryText.slice(0, 400))

// Genre/keyword search.
await evalJs(`(() => { const a = document.querySelector('a[href="/search"]'); if (a) a.click(); return !!a })()`)
await sleep(2500)
await evalJs(`(() => {
  const inp = document.querySelector('input[type="text"]')
  if (inp) { inp.value = 'dune'; inp.dispatchEvent(new Event('input', { bubbles: true })) }
  return !!inp
})()`)
await evalJs(`(() => { const b = document.querySelector('button'); if (b) b.click(); return !!b })()`)
await sleep(3500)
console.log('SEARCH RESULTS:', (await evalJs('document.body.innerText'))?.slice(0, 500))

const shot = await cdp(ws, 'Page.captureScreenshot', { format: 'png' })
writeFileSync('/tmp/libarr-ui-smoke.png', Buffer.from(shot.data, 'base64'))
console.log('screenshot: /tmp/libarr-ui-smoke.png')

chrome.kill()
process.exit(0)
