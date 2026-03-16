import asyncio
import boto3
import json
import urllib.request
import urllib.parse
from playwright.async_api import async_playwright

REGION   = "us-east-1"
APP_NAME = "DemoExternalAWSApp"

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

            # ── Navigate to Applications ──────────────────────────────────
            print("[PW] Navigating to Applications...")
            await page.goto(
                f"https://{REGION}.console.aws.amazon.com/singlesignon/home#/applications",
                timeout=60000,
                wait_until=LOAD
            )
            await page.wait_for_timeout(5000)
            await page.screenshot(path="pw_02_applications.png")
            print("[PW] On applications page")

            # ── Check what's visible ──────────────────────────────────────
            recommended_visible = await page.is_visible('button:has-text("Recommended")')
            add_app_visible     = await page.is_visible('button:has-text("Add application")')
            print(f"[PW] Recommended visible: {recommended_visible}")
            print(f"[PW] Add application visible: {add_app_visible}")

            if add_app_visible:
                print("[PW] Clicking Add application...")
                await page.click('button:has-text("Add application")')
                await page.wait_for_timeout(3000)
                await page.screenshot(path="pw_03_add_app.png")
            else:
                print("[PW] Already on wizard — skipping Add application click")
                await page.screenshot(path="pw_03_already_on_wizard.png")

            # ── Select Customer managed ───────────────────────────────────
            print("[PW] Selecting Customer managed application...")
            try:
                await page.wait_for_selector(
                    'button:has-text("Customer managed")',
                    timeout=10000
                )
                await page.click('button:has-text("Customer managed")')
                await page.wait_for_timeout(1000)
                await page.screenshot(path="pw_04_selected_type.png")
                print("[PW] Selected Customer managed")
            except Exception as e:
                print(f"[PW] Could not click Customer managed: {e}")
                await page.screenshot(path="pw_04_type_error.png")

            # ── Click Next ────────────────────────────────────────────────
            await page.wait_for_selector(
                'button:has-text("Next")', timeout=10000
            )
            await page.click('button:has-text("Next")')
            await page.wait_for_timeout(3000)
            await page.screenshot(path="pw_05_after_next.png")

            # ── Print visible buttons on next page ────────────────────────
            buttons = await page.query_selector_all("button")
            print("[PW] Buttons after Next:")
            for btn in buttons:
                try:
                    txt = await btn.inner_text()
                    vis = await btn.is_visible()
                    if txt.strip() and vis:
                        print(f"  button: '{txt.strip()}'")
                except Exception:
                    pass

            # ── Fill display name ─────────────────────────────────────────
            print(f"[PW] Filling app name: {APP_NAME}")
            filled = False
            for selector in [
                'input[id*="displayName"]',
                'input[placeholder*="isplay name"]',
                'input[name*="displayName"]',
                'input[name*="name"]',
                'input[type="text"]'
            ]:
                try:
                    await page.wait_for_selector(selector, timeout=5000)
                    await page.fill(selector, APP_NAME)
                    filled = True
                    print(f"[PW] Filled with selector: {selector}")
                    break
                except Exception:
                    continue

            if not filled:
                await page.screenshot(path="pw_fill_failed.png")
                raise Exception("Could not find display name input — check pw_fill_failed.png")

            await page.screenshot(path="pw_06_filled.png")

            # ── Submit ────────────────────────────────────────────────────
            print("[PW] Submitting...")
            await page.click('button:has-text("Submit")')
            await page.wait_for_timeout(4000)
            await page.screenshot(path="pw_07_submitted.png")
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
                await page.screenshot(path="pw_08_group_assigned.png")
                print("[PW] DemoGroup assigned")
            except Exception as e:
                print(f"[PW] Group assignment skipped: {e}")
                await page.screenshot(path="pw_08_group_error.png")

        except Exception as e:
            print(f"[PW ERROR] {e}")
            await page.screenshot(path="pw_error.png")
            raise

        finally:
            await browser.close()
            print("[PW] Done")


if __name__ == "__main__":
    asyncio.run(run())
