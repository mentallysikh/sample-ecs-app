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


async def debug_page(page, label):
    """Print all visible buttons and inputs, save screenshot."""
    await page.screenshot(path=f"{label}.png")
    buttons = await page.query_selector_all("button")
    print(f"[PW DEBUG] {label} — visible buttons:")
    for btn in buttons:
        try:
            txt = await btn.inner_text()
            vis = await btn.is_visible()
            if txt.strip() and vis:
                print(f"  btn: '{txt.strip()}'")
        except Exception:
            pass
    inputs = await page.query_selector_all("input")
    print(f"[PW DEBUG] {label} — visible inputs:")
    for inp in inputs:
        try:
            vis        = await inp.is_visible()
            itype      = await inp.get_attribute("type")
            iid        = await inp.get_attribute("id")
            iname      = await inp.get_attribute("name")
            iplaceholder = await inp.get_attribute("placeholder")
            if vis:
                print(f"  input type={itype} id={iid} name={iname} placeholder={iplaceholder}")
        except Exception:
            pass


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
            # ── Login ─────────────────────────────────────────────────────
            print("[PW] Opening federated session...")
            await page.goto(login_url, timeout=60000, wait_until=LOAD)
            await page.wait_for_timeout(3000)
            await debug_page(page, "pw_01_login")
            print("[PW] Logged in")

            # ── Go to add application URL directly ────────────────────────
            # Skip the list page entirely — go straight to the wizard
            print("[PW] Going directly to Add Application wizard...")
            await page.goto(
                f"https://{REGION}.console.aws.amazon.com"
                f"/singlesignon/home#/applications/add",
                timeout=60000,
                wait_until=LOAD
            )
            await page.wait_for_timeout(5000)
            await debug_page(page, "pw_02_add_wizard")

            # ── Click Customer managed tab ────────────────────────────────
            print("[PW] Clicking Customer managed tab...")
            try:
                await page.click('button:has-text("Customer managed")', timeout=10000)
                await page.wait_for_timeout(2000)
                await debug_page(page, "pw_03_customer_managed")
            except Exception as e:
                print(f"[PW] Customer managed tab: {e}")

            # ── Look for a SAML application card to click ─────────────────
            print("[PW] Looking for Custom SAML application card...")
            saml_clicked = False
            for selector in [
                'div:has-text("Custom SAML 2.0 application")',
                'span:has-text("Custom SAML 2.0")',
                '[data-testid*="saml"]',
                'label:has-text("Custom SAML")',
                'li:has-text("Custom SAML")'
            ]:
                try:
                    await page.click(selector, timeout=5000)
                    saml_clicked = True
                    print(f"[PW] Clicked SAML app with: {selector}")
                    await page.wait_for_timeout(1000)
                    break
                except Exception:
                    continue

            if not saml_clicked:
                print("[PW] Could not find SAML card — will try Next directly")

            await debug_page(page, "pw_04_before_next")

            # ── Click Next ────────────────────────────────────────────────
            print("[PW] Clicking Next...")
            await page.click('button:has-text("Next")', timeout=10000)
            await page.wait_for_timeout(4000)
            await debug_page(page, "pw_05_after_next")

            # ── Try clicking Next again if still on same page ─────────────
            still_has_recommended = await page.is_visible(
                'button:has-text("Recommended")'
            )
            if still_has_recommended:
                print("[PW] Still on type selection — clicking Next again...")
                await page.click('button:has-text("Next")', timeout=10000)
                await page.wait_for_timeout(4000)
                await debug_page(page, "pw_06_after_next2")

            # ── Fill display name ─────────────────────────────────────────
            print(f"[PW] Filling app name: {APP_NAME}")
            filled = False
            for selector in [
                'input[id*="displayName"]',
                'input[id*="name"]',
                'input[placeholder*="isplay"]',
                'input[placeholder*="ame"]',
                'input[name*="displayName"]',
                'input[name*="name"]',
                'input[type="text"]'
            ]:
                try:
                    el = await page.wait_for_selector(
                        selector, timeout=5000, state="visible"
                    )
                    await el.fill(APP_NAME)
                    filled = True
                    print(f"[PW] Filled with: {selector}")
                    break
                except Exception:
                    continue

            if not filled:
                await debug_page(page, "pw_fill_failed")
                raise Exception(
                    "Could not find display name input — check pw_fill_failed.png"
                )

            await page.screenshot(path="pw_07_filled.png")

            # ── Submit ────────────────────────────────────────────────────
            print("[PW] Submitting...")
            await page.click('button:has-text("Submit")', timeout=10000)
            await page.wait_for_timeout(4000)
            await page.screenshot(path="pw_08_submitted.png")
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
                await page.screenshot(path="pw_09_group_assigned.png")
                print("[PW] DemoGroup assigned")
            except Exception as e:
                print(f"[PW] Group assignment skipped: {e}")
                await page.screenshot(path="pw_09_group_error.png")

        except Exception as e:
            print(f"[PW ERROR] {e}")
            await page.screenshot(path="pw_error.png")
            raise

        finally:
            await browser.close()
            print("[PW] Done")


if __name__ == "__main__":
    asyncio.run(run())
