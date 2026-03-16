import asyncio
import os
from playwright.async_api import async_playwright

AWS_EMAIL    = os.environ.get("AWS_EMAIL", "")
AWS_PASSWORD = os.environ.get("AWS_PASSWORD", "")
REGION       = "us-east-1"
APP_NAME     = "DemoExternalAWSApp"

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page    = await context.new_page()

        print("[PW] Navigating to AWS Console login...")
        await page.goto("https://console.aws.amazon.com/console/home", timeout=60000)

        # ── Login ────────────────────────────────────────────────────────────
        await page.fill('input[name="email"]', AWS_EMAIL)
        await page.click('#next_button')
        await page.wait_for_timeout(2000)
        await page.fill('input[name="password"]', AWS_PASSWORD)
        await page.click('#signin_button')
        await page.wait_for_load_state("networkidle", timeout=60000)
        print("[PW] Logged in")

        # ── Navigate to IAM Identity Center ──────────────────────────────────
        await page.goto(
            f"https://{REGION}.console.aws.amazon.com/singlesignon/home",
            timeout=60000
        )
        await page.wait_for_load_state("networkidle")
        print("[PW] On IAM Identity Center page")

        # ── Go to Applications ────────────────────────────────────────────────
        await page.click('text=Applications')
        await page.wait_for_load_state("networkidle")
        print("[PW] On Applications page")

        # ── Add new application ───────────────────────────────────────────────
        await page.click('text=Add application')
        await page.wait_for_load_state("networkidle")

        # Select "I have an application I want to set up"
        await page.click('label:has-text("I have an application I want to set up")')
        await page.wait_for_timeout(1000)

        # Select "AWS managed" or custom — click Next
        await page.click('button:has-text("Next")')
        await page.wait_for_load_state("networkidle")

        # ── Fill app details ──────────────────────────────────────────────────
        await page.fill('input[placeholder*="display name"], input[id*="displayName"]', APP_NAME)
        print(f"[PW] Filled app name: {APP_NAME}")

        await page.click('button:has-text("Submit")')
        await page.wait_for_load_state("networkidle")
        print(f"[PW] Application '{APP_NAME}' created successfully")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
