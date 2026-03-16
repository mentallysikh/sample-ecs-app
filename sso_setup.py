import boto3
import json

REGION              = "us-east-1"
PERMISSION_SET_NAME = "DemoPermissionSet"
TARGET_ACCOUNT_ID   = "199570264160"
GROUP_NAME          = "DemoGroup"
USER_EMAIL          = "demo-user@example.com"
USER_FIRSTNAME      = "Demo"
USER_LASTNAME       = "User"
IDP_NAME            = "DemoIdP"
ROLE_NAME           = "DemoSSOFederatedRole"

sso = boto3.client("sso-admin",     region_name=REGION)
ids = boto3.client("identitystore", region_name=REGION)
iam = boto3.client("iam",           region_name=REGION)

def get_sso_instance():
    resp     = sso.list_instances()
    instance = resp["Instances"][0]
    print(f"[BOTO3] SSO Instance ARN : {instance['InstanceArn']}")
    print(f"[BOTO3] Identity Store ID: {instance['IdentityStoreId']}")
    return instance["InstanceArn"], instance["IdentityStoreId"]

def create_permission_set(instance_arn):
    try:
        resp = sso.create_permission_set(
            Name=PERMISSION_SET_NAME,
            InstanceArn=instance_arn,
            Description="Demo permission set created by Jenkins pipeline",
            SessionDuration="PT8H"
        )
        arn = resp["PermissionSet"]["PermissionSetArn"]
        print(f"[BOTO3] Permission Set created: {arn}")
    except sso.exceptions.ConflictException:
        pages = sso.get_paginator("list_permission_sets").paginate(
            InstanceArn=instance_arn
        )
        for page in pages:
            for ps_arn in page["PermissionSets"]:
                detail = sso.describe_permission_set(
                    InstanceArn=instance_arn,
                    PermissionSetArn=ps_arn
                )
                if detail["PermissionSet"]["Name"] == PERMISSION_SET_NAME:
                    arn = ps_arn
                    print(f"[BOTO3] Permission Set already exists: {arn}")
                    break
    sso.attach_managed_policy_to_permission_set(
        InstanceArn=instance_arn,
        PermissionSetArn=arn,
        ManagedPolicyArn="arn:aws:iam::aws:policy/ReadOnlyAccess"
    )
    print("[BOTO3] Attached ReadOnlyAccess to permission set")
    return arn

def create_idp():
    saml_metadata = """<?xml version="1.0"?>
<EntityDescriptor
  xmlns="urn:oasis:names:tc:SAML:2.0:metadata"
  entityID="https://demo-idp.example.com">
  <IDPSSODescriptor
    WantAuthnRequestsSigned="false"
    protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <SingleSignOnService
      Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
      Location="https://demo-idp.example.com/sso"/>
  </IDPSSODescriptor>
</EntityDescriptor>"""
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
        print(f"[BOTO3] Account assignment created for {TARGET_ACCOUNT_ID}")
    except sso.exceptions.ConflictException:
        print("[BOTO3] Account assignment already exists")

if __name__ == "__main__":
    print("=" * 50)
    print("  BOTO3 PHASE: Roles, IdP, Users, Groups")
    print("=" * 50)
    instance_arn, identity_store_id = get_sso_instance()
    ps_arn   = create_permission_set(instance_arn)
    idp_arn  = create_idp()
    create_iam_role(idp_arn)
    user_id  = create_user(identity_store_id)
    group_id = create_group(identity_store_id)
    add_user_to_group(identity_store_id, group_id, user_id)
    assign_account(instance_arn, ps_arn, group_id)
    print("=" * 50)
    print("  BOTO3 PHASE COMPLETE")
    print("=" * 50)
