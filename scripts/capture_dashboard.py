#!/usr/bin/env python3
import asyncio
import base64
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
import websockets

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUTPUT_PATH = Path(r"C:\Users\kp571\.gemini\antigravity\brain\a9cec8c0-02d7-4b8c-9100-29bd82866f9a\dashboard_verdict_strip.png")
PORT = 9222
USER_DATA = os.path.join(os.environ.get("TEMP", r"C:\Temp"), "chrome_cdp_test")

async def send_cdp(ws, method, params=None, msg_id=1):
    payload = {"id": msg_id, "method": method, "params": params or {}}
    await ws.send(json.dumps(payload))
    while True:
        resp = json.loads(await ws.recv())
        if resp.get("id") == msg_id:
            return resp.get("result", {})

async def main():
    print("Launching Chrome...")
    cmd = [
        CHROME_PATH,
        "--headless=new",
        f"--remote-debugging-port={PORT}",
        f"--user-data-dir={USER_DATA}",
        "--window-size=1280,960",
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    proc = subprocess.Popen(cmd)
    try:
        # Wait for debugging port
        ws_url = None
        for _ in range(30):
            try:
                data = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=1).read().decode())
                ws_url = data.get("webSocketDebuggerUrl")
                if ws_url:
                    break
            except Exception:
                time.sleep(0.3)
        if not ws_url:
            raise RuntimeError("Could not connect to Chrome debugging port")
        print(f"Connected to Chrome: {ws_url}")

        # Get existing pages from /json/list
        pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list").read().decode())
        page_ws_url = pages[0]["webSocketDebuggerUrl"]
        print(f"Target page ws: {page_ws_url}")

        async with websockets.connect(page_ws_url) as ws:
            msg_id = 1
            await send_cdp(ws, "Page.enable", msg_id=msg_id); msg_id += 1
            await send_cdp(ws, "Runtime.enable", msg_id=msg_id); msg_id += 1

            # Navigate to http://localhost:5000/
            await send_cdp(ws, "Page.navigate", {"url": "http://localhost:5000/"}, msg_id=msg_id); msg_id += 1

            # Wait for login page
            await asyncio.sleep(2)
            print("Logging in...")
            login_js = """
            (() => {
                const emailInput = document.querySelector('input[type="email"], input[name="email"], #email');
                const passInput = document.querySelector('input[type="password"], input[name="password"], #password');
                const submitBtn = document.querySelector('button[type="submit"], .btn-primary');
                if (emailInput && passInput) {
                    emailInput.value = 'admin';
                    emailInput.dispatchEvent(new Event('input', { bubbles: true }));
                    passInput.value = 'admin';
                    passInput.dispatchEvent(new Event('input', { bubbles: true }));
                    if (submitBtn) submitBtn.click();
                    return 'submitted';
                }
                return 'inputs_not_found';
            })()
            """
            res = await send_cdp(ws, "Runtime.evaluate", {"expression": login_js, "returnByValue": True}, msg_id=msg_id); msg_id += 1
            print("Login submit:", res)

            # Wait for redirect to dashboard
            await asyncio.sleep(3)
            url_res = await send_cdp(ws, "Runtime.evaluate", {"expression": "window.location.href", "returnByValue": True}, msg_id=msg_id); msg_id += 1
            print("Current URL:", url_res.get("result", {}).get("value"))

            # If still on login page or redirecting, wait a moment
            if "/dashboard" not in str(url_res.get("result", {}).get("value")):
                await send_cdp(ws, "Page.navigate", {"url": "http://localhost:5000/dashboard"}, msg_id=msg_id); msg_id += 1
                await asyncio.sleep(2)

            # Wait for camera tile to render
            await asyncio.sleep(3)

            # Trigger Scan plate
            scan_js = """
            (async () => {
                const scanBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Scan plate'));
                if (scanBtn) {
                    scanBtn.click();
                    return 'scan_button_clicked';
                }
                return 'scan_button_not_found';
            })()
            """
            scan_res = await send_cdp(ws, "Runtime.evaluate", {"expression": scan_js, "awaitPromise": True, "returnByValue": True}, msg_id=msg_id); msg_id += 1
            print("Scan trigger result:", scan_res)

            # Wait for scan response and verdict strip update
            await asyncio.sleep(4)

            # Check verdict strip contents
            strip_js = """
            (() => {
                const strip = document.querySelector('.verdict-strip');
                if (!strip) return { error: 'no verdict strip found' };
                const pills = Array.from(strip.querySelectorAll('.verdict-pill')).map(p => ({
                    className: p.className,
                    text: p.innerText.trim()
                }));
                const advice = strip.querySelector('.verdict-advice')?.innerText || '';
                return { pills, advice };
            })()
            """
            strip_res = await send_cdp(ws, "Runtime.evaluate", {"expression": strip_js, "returnByValue": True}, msg_id=msg_id); msg_id += 1
            print("Verdict strip status:\n", json.dumps(strip_res.get("result", {}).get("value"), indent=2))

            # Capture screenshot
            shot_res = await send_cdp(ws, "Page.captureScreenshot", {"format": "png"}, msg_id=msg_id); msg_id += 1
            img_b64 = shot_res.get("data", "")
            if img_b64:
                OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
                OUTPUT_PATH.write_bytes(base64.b64decode(img_b64))
                print(f"Screenshot successfully saved to: {OUTPUT_PATH}")
            else:
                print("Failed to capture screenshot data")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()

if __name__ == "__main__":
    asyncio.run(main())
