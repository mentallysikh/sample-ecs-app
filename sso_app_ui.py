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


async def click_next(page):
    """Click the last visible Next button on the page."""
    next_buttons = await page.query_selector_all('button:has-text("Next")')
    for btn in reversed(next_buttons):
        try:
            if await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(3000)
                return True
        except Exception:
            continue
    return False


async def dump_buttons(page, label):
    """Print all visible buttons and save screenshot."""
    await page.screenshot(path=f"{label}.png")
    buttons = await page.query_selector_all("button")
    print(f"[PW] {label} buttons:")
    for btn in buttons:
        try:
            txt = await btn.inner_text()
            if txt.strip() and await btn.is_visible():
                print(f"  '{txt.strip()}'")
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
            # ── Login via federation ──────────────────────────────────────
            print("[PW] Opening federated session...")
            await page.goto(login_url, timeout=60000, wait_until=LOAD)
            await page.wait_for_timeout(3000)
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
            await dump_buttons(page, "pw_01_wizard_start")

            # ── Step 1: Fill name and URL ─────────────────────────────────
            print(f"[PW] Step 1 — filling app name: {APP_NAME}")
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

            try:
                await page.fill(
                    'input[placeholder*="application URL"]',
                    APP_URL,
                    timeout=5000
                )
                print("[PW] App URL filled")
            except Exception:
                print("[PW] URL field not found — skipping")

            await page.screenshot(path="pw_02_step1_filled.png")

            # ── Step 1 → Next ─────────────────────────────────────────────
            print("[PW] Step 1 — clicking Next...")
            await click_next(page)
            await dump_buttons(page, "pw_03_step2")

            # ── Step 2: Keep clicking Next until we reach the final button ─
            step = 2
            while True:
                # Check if we've reached the final button
                for final_btn in ["Done", "Submit", "Create", "Finish"]:
                    if await page.is_visible(f'button:has-text("{final_btn}")'):
                        print(f"[PW] Found final button: '{final_btn}'")
                        await page.click(f'button:has-text("{final_btn}")')
                        await page.wait_for_timeout(4000)
                        await page.screenshot(path="pw_final_submitted.png")
                        print(f"[PW] Application '{APP_NAME}' created!")
                        # Break out of while loop
                        raise StopIteration

                # Still have Next — click it
                next_visible = await page.is_visible('button:has-text("Next")')
                if next_visible:
                    print(f"[PW] Step {step} — clicking Next...")
                    await click_next(page)
                    step += 1
                    await dump_buttons(page, f"pw_0{step+2}_step{step}")
                else:
                    # No Next and no final button — something went wrong
                    await page.screenshot(path="pw_stuck.png")
                    raise Exception(
                        f"Stuck on step {step} — no Next or final button found"
                    )

        except StopIteration:
            # Successfully clicked the final button
            pass

        except Exception as e:
            print(f"[PW ERROR] {e}")
            await page.screenshot(path="pw_error.png")
            raise

        finally:
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
                await page.screenshot(path="pw_group_assigned.png")
                print("[PW] DemoGroup assigned")
            except Exception as e:
                print(f"[PW] Group assignment skipped: {e}")
                await page.screenshot(path="pw_group_error.png")

            await browser.close()
            print("[PW] Done")


if __name__ == "__main__":
    asyncio.run(run())
