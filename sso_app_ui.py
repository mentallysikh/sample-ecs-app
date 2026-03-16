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

        try:
            # Login via federation
            print("[PW] Opening federated session...")
            await page.goto(login_url, timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=60000)
            await page.screenshot(path="pw_01_login.png")
            print("[PW] Logged in")

            # Go to Applications
            print("[PW] Navigating to Applications...")
            await page.goto(
                f"https://{REGION}.console.aws.amazon.com"
                f"/singlesignon/home#/applications",
                timeout=60000
            )
            await page.wait_for_load_state("networkidle")
            await page.screenshot(path="pw_02_applications.png")

            # Click Add application
            print("[PW] Clicking Add application...")
            await page.click('button:has-text("Add application")', timeout=15000)
            await page.wait_for_load_state("networkidle")
            await page.screenshot(path="pw_03_add_app.png")

            # Select custom app
            print("[PW] Selecting custom application...")
            try:
                await page.click(
                    'label:has-text("I have an application I want to set up")',
                    timeout=10000
                )
            except Exception:
                await page.click('input[type="radio"]', timeout=10000)

            await page.wait_for_timeout(1000)
            await page.click('button:has-text("Next")')
            await page.wait_for_load_state("networkidle")
            await page.screenshot(path="pw_04_app_details.png")

            # Fill name
            print(f"[PW] Filling app name: {APP_NAME}")
            for selector in [
                'input[id*="displayName"]',
                'input[placeholder*="isplay name"]',
                'input[name*="displayName"]',
                'input[type="text"]'
            ]:
                try:
                    await page.fill(selector, APP_NAME, timeout=5000)
                    print(f"[PW] Filled with selector: {selector}")
                    break
                except Exception:
                    continue

            await page.screenshot(path="pw_05_filled.png")

            # Submit
            print("[PW] Submitting...")
            await page.click('button:has-text("Submit")')
            await page.wait_for_load_state("networkidle")
            await page.screenshot(path="pw_06_submitted.png")
            print(f"[PW] Application '{APP_NAME}' created successfully")

            # Assign group
            print("[PW] Assigning DemoGroup...")
            try:
                await page.click(
                    'button:has-text("Assign users and groups")',
                    timeout=10000
                )
                await page.wait_for_load_state("networkidle")
                await page.fill(
                    'input[type="search"]', "DemoGroup"
                )
                await page.wait_for_timeout(2000)
                await page.click('input[type="checkbox"]')
                await page.click('button:has-text("Assign")')
                await page.wait_for_load_state("networkidle")
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
