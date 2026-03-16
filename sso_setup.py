import boto3
import json

# ── Config ──────────────────────────────────────────────────────────────────
SOURCE_INSTANCE_ARN   = None   # filled automatically below
PERMISSION_SET_NAME   = "DemoPermissionSet"
TARGET_ACCOUNT_ID     = "199570264160"   # replace if you have a second account
REGION                = "us-east-1"
GROUP_NAME            = "DemoGroup"
USER_EMAIL            = "demo-user@example.com"
USER_FIRSTNAME        = "Demo"
USER_LASTNAME         = "User"
# ────────────────────────────────────────────────────────────────────────────

sso   = boto3.client("sso-admin",        region_name=REGION)
ids   = boto3.client("identitystore",    region_name=REGION)
iam   = boto3.client("iam",              region_name=REGION)

# ── 1. Get SSO Instance ARN & Identity Store ID ──────────────────────────────
def get_sso_instance():
    resp = sso.list_instances()
    instance = resp["Instances"][0]
    print(f"[INFO] SSO Instance ARN : {instance['InstanceArn']}")
    print(f"[INFO] Identity Store ID: {instance['IdentityStoreId']}")
    return instance["InstanceArn"], instance["IdentityStoreId"]

# ── 2. Create Permission Set ──────────────────────────────────────────────────
def create_permission_set(instance_arn):
    try:
        resp = sso.create_permission_set(
            Name=PERMISSION_SET_NAME,
            InstanceArn=instance_arn,
            Description="Demo permission set created by Jenkins pipeline",
            SessionDuration="PT8H"
        )
        arn = resp["PermissionSet"]["PermissionSetArn"]
        print(f"[INFO] Permission Set created: {arn}")
    except sso.exceptions.ConflictException:
        # Already exists — fetch it
        pages = sso.get_paginator("list_permission_sets").paginate(InstanceArn=instance_arn)
        for page in pages:
            for ps_arn in page["PermissionSets"]:
                detail = sso.describe_permission_set(InstanceArn=instance_arn, PermissionSetArn=ps_arn)
                if detail["PermissionSet"]["Name"] == PERMISSION_SET_NAME:
                    arn = ps_arn
                    print(f"[INFO] Permission Set already exists: {arn}")
                    break

    # Attach ReadOnly managed policy
    sso.attach_managed_policy_to_permission_set(
        InstanceArn=instance_arn,
        PermissionSetArn=arn,
        ManagedPolicyArn="arn:aws:iam::aws:policy/ReadOnlyAccess"
    )
    print("[INFO] Attached ReadOnlyAccess policy")
    return arn

# ── 3. Create Demo User ───────────────────────────────────────────────────────
def create_user(identity_store_id):
    try:
        resp = ids.create_user(
            IdentityStoreId=identity_store_id,
            UserName=USER_EMAIL,
            Name={"GivenName": USER_FIRSTNAME, "FamilyName": USER_LASTNAME},
            Emails=[{"Value": USER_EMAIL, "Type": "work", "Primary": True}]
        )
        user_id = resp["UserId"]
        print(f"[INFO] User created: {user_id}")
    except ids.exceptions.ConflictException:
        resp = ids.get_user_id(
            IdentityStoreId=identity_store_id,
            AlternateIdentifier={"UniqueAttribute": {"AttributePath": "userName", "AttributeValue": USER_EMAIL}}
        )
        user_id = resp["UserId"]
        print(f"[INFO] User already exists: {user_id}")
    return user_id

# ── 4. Create Demo Group ──────────────────────────────────────────────────────
def create_group(identity_store_id):
    try:
        resp = ids.create_group(
            IdentityStoreId=identity_store_id,
            DisplayName=GROUP_NAME,
            Description="Demo group for SSO pipeline"
        )
        group_id = resp["GroupId"]
        print(f"[INFO] Group created: {group_id}")
    except ids.exceptions.ConflictException:
        resp = ids.get_group_id(
            IdentityStoreId=identity_store_id,
            AlternateIdentifier={"UniqueAttribute": {"AttributePath": "displayName", "AttributeValue": GROUP_NAME}}
        )
        group_id = resp["GroupId"]
        print(f"[INFO] Group already exists: {group_id}")
    return group_id

# ── 5. Add User to Group ──────────────────────────────────────────────────────
def add_user_to_group(identity_store_id, group_id, user_id):
    try:
        ids.create_group_membership(
            IdentityStoreId=identity_store_id,
            GroupId=group_id,
            MemberId={"UserId": user_id}
        )
        print("[INFO] User added to group")
    except ids.exceptions.ConflictException:
        print("[INFO] User already in group")

# ── 6. Assign Permission Set to Account ──────────────────────────────────────
def assign_account(instance_arn, permission_set_arn, group_id):
    try:
        sso.create_account_assignment(
            InstanceArn=instance_arn,
            TargetId=TARGET_ACCOUNT_ID,
            TargetType="AWS_ACCOUNT",
            PermissionSetArn=permission_set_arn,
            PrincipalType="GROUP",
            PrincipalId=group_id
        )
        print(f"[INFO] Account assignment created for account {TARGET_ACCOUNT_ID}")
    except sso.exceptions.ConflictException:
        print("[INFO] Account assignment already exists")

# ── 7. Create IAM Role in Target Account (IdP trust) ─────────────────────────
def create_iam_role():
    trust_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Federated": f"arn:aws:iam::{TARGET_ACCOUNT_ID}:saml-provider/DemoIdP"},
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
            RoleName="DemoSSORole",
            AssumeRolePolicyDocument=trust_policy,
            Description="Role for SSO demo pipeline"
        )
        print("[INFO] IAM Role DemoSSORole created")
    except iam.exceptions.EntityAlreadyExistsException:
        print("[INFO] IAM Role already exists")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== SSO Setup: boto3 phase ===")
    instance_arn, identity_store_id = get_sso_instance()
    ps_arn   = create_permission_set(instance_arn)
    user_id  = create_user(identity_store_id)
    group_id = create_group(identity_store_id)
    add_user_to_group(identity_store_id, group_id, user_id)
    assign_account(instance_arn, ps_arn, group_id)
    create_iam_role()
    print("=== boto3 phase complete ===")
