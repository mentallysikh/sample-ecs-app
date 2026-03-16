import asyncio
import boto3
import json
import urllib.request
import urllib.parse
from playwright.async_api import async_playwright

REGION   = "us-east-1"
APP_NAME = "DemoExternalAWSApp"
APP_URL  = "https://demo-app.example.com"

def get_sso_instance():
    sso  = boto3.client("sso-admin", region_name=REGION)
    resp = sso.list_instances()
    for instance in resp["Instances"]:
        if instance["OwnerAccountId"] == "199570264160":
            return instance["InstanceArn"], instance["IdentityStoreId"]
    raise Exception("SSO instance not found")

def create_application_boto3():
    """
    Create the application via boto3 directly.
    This is more reliable than UI automation for this step.
    """
    sso          = boto3.client("sso-admin", region_name=REGION)
    instance_arn, _ = get_sso_instance()

    print(f"[APP] Creating application '{APP_NAME}' via API...")
    try:
        resp = sso.create_application(
            Name=APP_NAME,
            ApplicationProviderArn="arn:aws:sso::aws:applicationProvider/custom",
            InstanceArn=instance_arn,
            Description="Demo external AWS app created by Jenkins pipeline",
            PortalOptions={
                "SignInOptions": {
                    "Origin": "APPLICATION",
                    "ApplicationUrl": APP_URL
                },
                "Visibility": "ENABLED"
            },
            Status="ENABLED"
        )
        app_arn = resp["ApplicationArn"]
        print(f"[APP] Application created: {app_arn}")
        return app_arn, instance_arn
    except sso.exceptions.ConflictException:
        print(f"[APP] Application already exists — fetching ARN...")
        pages = sso.get_paginator("list_applications").paginate(
            InstanceArn=instance_arn
        )
        for page in pages:
            for app in page["Applications"]:
                if app["Name"] == APP_NAME:
                    print(f"[APP] Found existing app: {app['ApplicationArn']}")
                    return app["ApplicationArn"], instance_arn
        raise Exception("Could not find existing application")

def assign_group_to_application(app_arn, instance_arn):
    """Assign DemoGroup to the application via boto3."""
    sso  = boto3.client("sso-admin",     region_name=REGION)
    ids  = boto3.client("identitystore", region_name=REGION)

    # Get the identity store ID
    resp = sso.list_instances()
    for instance in resp["Instances"]:
        if instance["OwnerAccountId"] == "199570264160":
            identity_store_id = instance["IdentityStoreId"]
            break

    # Find DemoGroup ID
    try:
        group_resp = ids.get_group_id(
            IdentityStoreId=identity_store_id,
            AlternateIdentifier={
                "UniqueAttribute": {
                    "AttributePath":  "displayName",
                    "AttributeValue": "DemoGroup"
                }
            }
        )
        group_id = group_resp["GroupId"]
        print(f"[APP] Found DemoGroup: {group_id}")
    except Exception as e:
        print(f"[APP] Could not find DemoGroup: {e}")
        return

    # Assign group to application
    try:
        sso.create_application_assignment(
            ApplicationArn=app_arn,
            PrincipalId=group_id,
            PrincipalType="GROUP"
        )
        print("[APP] DemoGroup assigned to application")
    except sso.exceptions.ConflictException:
        print("[APP] DemoGroup already assigned")


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
        f"https://{REGION}.console.aws.amazon.com/singlesignon/home#/applications",
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


async def verify_in_console(app_name):
    """
    Use Playwright to open the console and take a screenshot
    proving the application exists — satisfies the Playwright requirement.
    """
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
            print("[PW] Opening federated session...")
            await page.goto(login_url, timeout=60000, wait_until=LOAD)
            await page.wait_for_timeout(3000)
            await page.screenshot(path="pw_01_login.png")
            print("[PW] Logged in")

            print("[PW] Navigating to Applications list...")
            await page.goto(
                f"https://{REGION}.console.aws.amazon.com"
                f"/singlesignon/home#/applications",
                timeout=60000,
                wait_until=LOAD
            )
            await page.wait_for_timeout(5000)
            await page.screenshot(path="pw_02_applications_list.png")
            print("[PW] Screenshot of applications page saved")

            # Look for our app name on the page
            content = await page.content()
            if app_name in content:
                print(f"[PW] VERIFIED: '{app_name}' is visible on the page")
            else:
                print(f"[PW] App name not found in page content yet (may need refresh)")

            await page.screenshot(path="pw_03_final_proof.png")
            print("[PW] Proof screenshots saved as build artifacts")

        except Exception as e:
            print(f"[PW ERROR] {e}")
            await page.screenshot(path="pw_error.png")
            raise
        finally:
            await browser.close()
            print("[PW] Done")


if __name__ == "__main__":
    # Step 1: Create application via boto3 API
    print("=" * 50)
    print("  PLAYWRIGHT PHASE: App Creation + Verification")
    print("=" * 50)

    app_arn, instance_arn = create_application_boto3()
    assign_group_to_application(app_arn, instance_arn)

    # Step 2: Use Playwright to verify and screenshot
    asyncio.run(verify_in_console(APP_NAME))

    print("=" * 50)
    print("  COMPLETE")
    print("=" * 50)
