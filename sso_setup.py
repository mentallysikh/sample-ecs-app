import boto3
import json

REGION             = "us-east-1"
TARGET_ACCOUNT_ID  = "199570264160"
GROUP_NAME         = "DemoGroup"
USER_EMAIL         = "demo-user@example.com"
USER_FIRSTNAME     = "Demo"
USER_LASTNAME      = "User"
IDP_NAME           = "DemoIdP"
ROLE_NAME          = "DemoSSOFederatedRole"

sso = boto3.client("sso-admin",     region_name=REGION)
ids = boto3.client("identitystore", region_name=REGION)
iam = boto3.client("iam",           region_name=REGION)

# ── 1. Get SSO Instance ───────────────────────────────────────────────────────
def get_sso_instance():
    resp = sso.list_instances()
    # Pick the instance owned by THIS account (sandbox)
    for instance in resp["Instances"]:
        if instance["OwnerAccountId"] == TARGET_ACCOUNT_ID:
            print(f"[BOTO3] SSO Instance ARN : {instance['InstanceArn']}")
            print(f"[BOTO3] Identity Store ID: {instance['IdentityStoreId']}")
            return instance["InstanceArn"], instance["IdentityStoreId"]
    raise Exception(f"No SSO instance found for account {TARGET_ACCOUNT_ID}")

# ── 2. Create IdP (SAML Provider) ─────────────────────────────────────────────
def create_idp():
    import subprocess
    import os

    # Generate cert if it doesn't exist
    if not os.path.exists("/tmp/idp-cert.pem"):
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", "/tmp/idp-key.pem",
            "-out", "/tmp/idp-cert.pem",
            "-days", "365", "-nodes",
            "-subj", "/CN=demo-idp/O=Demo/C=US"
        ], check=True, capture_output=True)
        print("[BOTO3] Generated self-signed certificate")

    # Read certificate content
    cert_result = subprocess.run(
        "openssl x509 -in /tmp/idp-cert.pem -outform PEM | grep -v 'BEGIN\\|END' | tr -d '\\n'",
        shell=True, capture_output=True, text=True, check=True
    )
    cert = cert_result.stdout.strip()

    saml_metadata = f"""<?xml version="1.0" encoding="UTF-8"?>
<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" xmlns:ds="http://www.w3.org/2000/09/xmldsig#" entityID="https://demo-idp.example.com">
  <IDPSSODescriptor WantAuthnRequestsSigned="false" protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <KeyDescriptor use="signing">
      <ds:KeyInfo>
        <ds:X509Data>
          <ds:X509Certificate>{cert}</ds:X509Certificate>
        </ds:X509Data>
      </ds:KeyInfo>
    </KeyDescriptor>
    <NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</NameIDFormat>
    <SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="https://demo-idp.example.com/sso/saml"/>
    <SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="https://demo-idp.example.com/sso/saml"/>
  </IDPSSODescriptor>
</EntityDescriptor>"""

    print(f"[BOTO3] Metadata length: {len(saml_metadata)} chars")

    try:
        resp    = iam.create_saml_provider(
            SAMLMetadataDocument=saml_metadata,
            Name=IDP_NAME
        )
        idp_arn = resp["SAMLProviderArn"]
        print(f"[BOTO3] IdP created: {idp_arn}")
    except iam.exceptions.EntityAlreadyExistsException:
        idp_arn = f"arn:aws:iam::{TARGET_ACCOUNT_ID}:saml-provider/{IDP_NAME}"
        print(f"[BOTO3] IdP already exists: {idp_arn}")
    return idp_arn

# ── 3. Create IAM Role with IdP Trust ─────────────────────────────────────────
def create_iam_role(idp_arn):
    trust_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Federated": idp_arn},
            "Action": "sts:AssumeRoleWithSAML",
            "Condition": {
                "StringEquals": {
                    "SAML:aud": "https://signin.aws.amazon.com/saml"
                }
            }
        }]
    })
    try:
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=trust_policy,
            Description="Federated role trusting DemoIdP — created by Jenkins"
        )
        iam.attach_role_policy(
            RoleName=ROLE_NAME,
            PolicyArn="arn:aws:iam::aws:policy/ReadOnlyAccess"
        )
        print(f"[BOTO3] IAM Role '{ROLE_NAME}' created with IdP trust")
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"[BOTO3] IAM Role '{ROLE_NAME}' already exists")

# ── 4. Create User ─────────────────────────────────────────────────────────────
def create_user(identity_store_id):
    try:
        resp    = ids.create_user(
            IdentityStoreId=identity_store_id,
            UserName=USER_EMAIL,
            Name={"GivenName": USER_FIRSTNAME, "FamilyName": USER_LASTNAME},
            Emails=[{"Value": USER_EMAIL, "Type": "work", "Primary": True}]
        )
        user_id = resp["UserId"]
        print(f"[BOTO3] User created: {user_id}")
    except ids.exceptions.ConflictException:
        resp    = ids.get_user_id(
            IdentityStoreId=identity_store_id,
            AlternateIdentifier={
                "UniqueAttribute": {
                    "AttributePath":  "userName",
                    "AttributeValue": USER_EMAIL
                }
            }
        )
        user_id = resp["UserId"]
        print(f"[BOTO3] User already exists: {user_id}")
    return user_id

# ── 5. Create Group ────────────────────────────────────────────────────────────
def create_group(identity_store_id):
    try:
        resp     = ids.create_group(
            IdentityStoreId=identity_store_id,
            DisplayName=GROUP_NAME,
            Description="Demo group for SSO pipeline"
        )
        group_id = resp["GroupId"]
        print(f"[BOTO3] Group created: {group_id}")
    except ids.exceptions.ConflictException:
        resp     = ids.get_group_id(
            IdentityStoreId=identity_store_id,
            AlternateIdentifier={
                "UniqueAttribute": {
                    "AttributePath":  "displayName",
                    "AttributeValue": GROUP_NAME
                }
            }
        )
        group_id = resp["GroupId"]
        print(f"[BOTO3] Group already exists: {group_id}")
    return group_id

# ── 6. Add User to Group ───────────────────────────────────────────────────────
def add_user_to_group(identity_store_id, group_id, user_id):
    try:
        ids.create_group_membership(
            IdentityStoreId=identity_store_id,
            GroupId=group_id,
            MemberId={"UserId": user_id}
        )
        print("[BOTO3] User added to group")
    except ids.exceptions.ConflictException:
        print("[BOTO3] User already in group")

# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  BOTO3 PHASE: IdP, Role, Users, Groups")
    print("=" * 50)

    instance_arn, identity_store_id = get_sso_instance()
    idp_arn  = create_idp()
    create_iam_role(idp_arn)
    user_id  = create_user(identity_store_id)
    group_id = create_group(identity_store_id)
    add_user_to_group(identity_store_id, group_id, user_id)

    print("=" * 50)
    print("  BOTO3 PHASE COMPLETE")
    print("=" * 50)
