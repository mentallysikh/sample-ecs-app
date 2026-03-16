import asyncio
import boto3
import json
import urllib.request
import urllib.parse
from playwright.async_api import async_playwright

REGION   = "us-east-1"
APP_NAME = "DemoExternalAWSApp"
APP_URL  = "https://demo-app.example.com"

def get_federation_url():
    print("[FED] Getting temporary credentials from instance role...")
    sts      = boto3.client("sts", region_name=REGION)
    identity = sts.get_caller_identity()
    print(f"[FED] Running as: {identity['Arn']}")

    session      = boto3.Session()
    creds        = session.get_credentials().get_frozen_credentials()
    session_json = json.dumps({
        "sessionId":    creds.access_key,
        "sessionKey":   creds.secret_key,
        "sessionToken": creds.token
    })

    params = urllib.parse.urlencode({
        "Action":          "getSigninToken",
        "SessionDuration": "3600",
        "Session":         session_json
    })
    with urllib.request.urlopen(
        f"https://signin.aws.amazon.com/federation?{params}"
    ) as response:
        signin_token = json.loads(response.read())["SigninToken"]

    destination = urllib.parse.quote(
        f"https://{REGION}.console.aws.amazon.com/singlesignon/home",
        safe=""
    )
    login_url = (
        f"https://signin.aws.amazon.com/federation"
        f"?Action=login"
        f"&Issuer=jenkins-pipeline"
        f"&Destination={destination}"
        f"&SigninToken={signin_token}"
    )
    print("[FED] Federation URL generated")
    return login_url


async def run():
    login_url = get_federation_url()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()
        LOAD = "domcontentloaded"

        try:
            # ── Login via federation ──────────────────────────────────────
            print("[PW] Opening federated session...")
            await page.goto(login_url, timeout=60000, wait_until=LOAD)
            await page.wait_for_timeout(3000)
            await page.screenshot(path="pw_01_login.png")
            print("[PW] Logged in")

            # ── Go directly to Add Application wizard ─────────────────────
            print("[PW] Navigating to Add Application wizard...")
            await page.goto(
                f"https://{REGION}.console.aws.amazon.com"
                f"/singlesignon/home#/applications/add",
                timeout=60000,
                wait_until=LOAD
            )
            await page.wait_for_timeout(5000)
            await page.screenshot(path="pw_02_wizard.png")
            print("[PW] On wizard page")

            # ── Fill display name ─────────────────────────────────────────
            # Confirmed selector from debug: placeholder="Enter an application display name"
            print(f"[PW] Filling app name: {APP_NAME}")
            await page.wait_for_selector(
                'input[placeholder*="application display name"]',
                timeout=15000,
                state="visible"
            )
            await page.fill(
                'input[placeholder*="application display name"]',
                APP_NAME
            )
            print("[PW] App name filled")
            await page.screenshot(path="pw_03_name_filled.png")

            # ── Fill application URL ──────────────────────────────────────
            print("[PW] Filling application URL...")
            try:
                await page.fill(
                    'input[placeholder*="application URL"]',
                    APP_URL,
                    timeout=5000
                )
                print("[PW] App URL filled")
            except Exception:
                print("[PW] URL field not found — skipping")

            await page.screenshot(path="pw_04_url_filled.png")

            # ── Click Next ────────────────────────────────────────────────
            print("[PW] Clicking Next...")
            next_buttons = await page.query_selector_all('button:has-text("Next")')
            for btn in reversed(next_buttons):
                try:
                    vis = await btn.is_visible()
                    if vis:
                        await btn.click()
                        print("[PW] Clicked Next")
                        break
                except Exception:
                    continue

            await page.wait_for_timeout(3000)
            await page.screenshot(path="pw_05_after_next.png")

            # ── Debug: what's on this page? ───────────────────────────────
            buttons = await page.query_selector_all("button")
            print("[PW] Buttons after Next:")
            for btn in buttons:
                try:
                    txt = await btn.inner_text()
                    vis = await btn.is_visible()
                    if txt.strip() and vis:
                        print(f"  btn: '{txt.strip()}'")
                except Exception:
                    pass

            inputs = await page.query_selector_all("input")
            print("[PW] Inputs after Next:")
            for inp in inputs:
                try:
                    vis = await inp.is_visible()
                    iplaceholder = await inp.get_attribute("placeholder")
                    itype = await inp.get_attribute("type")
                    if vis:
                        print(f"  input type={itype} placeholder={iplaceholder}")
                except Exception:
                    pass

            # ── Click whatever the final button is ────────────────────────
            print("[PW] Looking for final action button...")
            for btn_text in ["Done", "Submit", "Create", "Finish", "Save", "Next"]:
                try:
                    btn = page.locator(f'button:has-text("{btn_text}")')
                    if await btn.is_visible(timeout=3000):
                        await btn.click()
                        print(f"[PW] Clicked '{btn_text}'")
                        await page.wait_for_timeout(3000)
                        await page.screenshot(path="pw_06_final.png")
                        break
                except Exception:
                    continue
            # ── Click Done ────────────────────────────────────────────────
            # Confirmed from debug: button says "Done" not "Submit"
            print("[PW] Clicking Done...")
            await page.wait_for_selector(
                'button:has-text("Done")',
                timeout=10000,
                state="visible"
            )
            await page.click('button:has-text("Done")')
            await page.wait_for_timeout(4000)
            await page.screenshot(path="pw_06_done.png")
            print(f"[PW] Application '{APP_NAME}' created successfully")

            # ── Assign DemoGroup ──────────────────────────────────────────
            print("[PW] Assigning DemoGroup...")
            try:
                await page.wait_for_selector(
                    'button:has-text("Assign users and groups")',
                    timeout=10000
                )
                await page.click('button:has-text("Assign users and groups")')
                await page.wait_for_timeout(2000)
                await page.fill('input[type="search"]', "DemoGroup")
                await page.wait_for_timeout(2000)
                await page.click('input[type="checkbox"]')
                await page.wait_for_timeout(500)
                await page.click('button:has-text("Assign")')
                await page.wait_for_timeout(2000)
                await page.screenshot(path="pw_07_group_assigned.png")
                print("[PW] DemoGroup assigned")
            except Exception as e:
                print(f"[PW] Group assignment skipped: {e}")
                await page.screenshot(path="pw_07_group_error.png")

        except Exception as e:
            print(f"[PW ERROR] {e}")
            await page.screenshot(path="pw_error.png")
            raise

        finally:
            await browser.close()
            print("[PW] Done")


if __name__ == "__main__":
    asyncio.run(run())
