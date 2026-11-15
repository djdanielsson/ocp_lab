"""Reconcile the lab identity through the Keycloak and Kubernetes APIs.

Credentials are mounted files. Failures omit response bodies and credentials.
No third party Python packages or command line secrets are required.
"""

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


class ReconcileError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class API:
    def __init__(self, base, token=None, ca=None, headers=None):
        self.base = base.rstrip("/")
        self.token = token
        self.headers = dict(headers or {})
        context = ssl.create_default_context(cafile=ca)
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPSHandler(context=context)
        )

    def request(self, method, path, body=None, missing=False, form=None,
                content_type="application/json"):
        headers = {"Accept": "application/json", **self.headers}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = content_type
        elif form is not None:
            data = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(self.base + path, data, headers, method=method)
        try:
            with self.opener.open(req, timeout=30) as response:
                data = response.read()
                return json.loads(data) if data else None
        except urllib.error.HTTPError as error:
            if missing and error.code == 404:
                return None
            # Do not print response bodies: they may contain credentials/tokens.
            raise ReconcileError(f"{method} {path.split('?')[0]}: HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            # Do not replay writes after an ambiguous transport failure. The
            # next scheduled run reads current state before trying again.
            raise ReconcileError(f"{method} {path.split('?')[0]}: transport failed") from None


def read_secret(directory, key):
    value = (Path(directory) / key).read_text()
    if not value:
        raise ReconcileError("A required mounted credential is empty")
    return value


def upsert_client(api, realm, config, credentials, supplied_secret=None):
    client = dict(config)
    secret_key = client.pop("secretKey", None)
    pkce = client.pop("pkce", False)
    extra_mappers = client.pop("additionalProtocolMappers", [])
    client.update({
        "protocol": "openid-connect", "enabled": True,
        "standardFlowEnabled": True, "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False, "serviceAccountsEnabled": False,
        "publicClient": secret_key is None and supplied_secret is None,
        "defaultClientScopes": ["web-origins", "acr", "profile", "email", "roles"],
        "optionalClientScopes": ["offline_access"],
        "protocolMappers": [{
            "name": "groups", "protocol": "openid-connect",
            "protocolMapper": "oidc-group-membership-mapper",
            "config": {"claim.name": "groups", "full.path": "false",
                       "id.token.claim": "true", "access.token.claim": "true",
                       "userinfo.token.claim": "true"},
        }],
    })
    client["protocolMappers"].extend(extra_mappers)
    if pkce:
        client.setdefault("attributes", {})["pkce.code.challenge.method"] = "S256"
    if secret_key or supplied_secret is not None:
        client["secret"] = supplied_secret if supplied_secret is not None else read_secret(credentials, secret_key)
        client["clientAuthenticatorType"] = "client-secret"
    path = realm + "/clients"
    existing = api.request("GET", path + "?" + urllib.parse.urlencode({"clientId": client["clientId"]}))
    if len(existing) > 1:
        raise ReconcileError("An OIDC client ID is ambiguous")
    if existing:
        api.request("PUT", path + "/" + existing[0]["id"], client)
    else:
        api.request("POST", path, client)


def reconcile_user(api, realm, config, admin_password, user_dir):
    username = read_secret(user_dir, "username")
    password = read_secret(user_dir, "password")
    if username != username.strip() or not username.strip():
        raise ReconcileError("The Vaultwarden SSO username has surrounding whitespace")
    # The login stays exactly as stored in Vaultwarden. Set user.email in
    # settings.json to override the fallback address for OIDC applications.
    email = config.get("email") or (username if "@" in username else username + "@" + config["emailDomain"])
    if "@" not in email or any(c.isspace() for c in email):
        raise ReconcileError("Configure a valid SSO email address in settings.json")
    path = realm + "/users"
    query = urllib.parse.urlencode({"username": username, "exact": "true"})
    matches = api.request("GET", path + "?" + query)
    if len(matches) > 1:
        raise ReconcileError("The SSO username is ambiguous")
    existing = matches[0] if matches else None
    marker = "lab-sso-managed"
    if existing and existing.get("attributes", {}).get(marker) != ["true"]:
        raise ReconcileError("The SSO username already exists outside this reconciler; explicit migration is required")
    # A keyed fingerprint avoids resetting the password on every run and does
    # not expose an unkeyed password hash in user attributes.
    version = hmac.new(admin_password.encode(), (username + "\0" + password).encode(), hashlib.sha256).hexdigest()
    attributes = dict((existing or {}).get("attributes", {}))
    previous_version = attributes.get("lab-sso-password-version")
    attributes[marker] = ["true"]
    user = {"username": username, "email": email, "emailVerified": True,
            "firstName": config.get("firstName") or username,
            "lastName": config.get("lastName") or "Lab",
            "enabled": config.get("enabled", True), "attributes": attributes}
    if not existing:
        user["credentials"] = [{"type": "password", "value": password, "temporary": False}]
        attributes["lab-sso-password-version"] = [version]
        api.request("POST", path, user)
        matches = api.request("GET", path + "?" + query)
        if len(matches) != 1:
            raise ReconcileError("Cannot resolve the newly created SSO account")
        existing = matches[0]
    user_path = path + "/" + existing["id"]
    if previous_version != [version] and "credentials" not in user:
        api.request("PUT", user_path + "/reset-password",
                    {"type": "password", "value": password, "temporary": False})
        # Invalidate sessions after password rotation or an explicit disable.
        api.request("POST", user_path + "/logout")
    attributes["lab-sso-password-version"] = [version]
    user.pop("credentials", None)
    api.request("PUT", user_path, user)
    if not user["enabled"]:
        api.request("POST", user_path + "/logout")
    policy_groups = config.get("policyGroups", [])
    for name in ["lab-users", "lab-admins"] + [g["name"] for g in policy_groups]:
        groups_path = realm + "/groups"
        groups = api.request("GET", groups_path + "?" + urllib.parse.urlencode({"search": name, "exact": "true"}))
        groups = [g for g in groups if g["name"] == name]
        if not groups:
            api.request("POST", groups_path, {"name": name})
            groups = api.request("GET", groups_path + "?" + urllib.parse.urlencode({"search": name, "exact": "true"}))
            groups = [g for g in groups if g["name"] == name]
        if len(groups) != 1:
            raise ReconcileError("Cannot resolve a managed SSO group")
        member = (name == "lab-users" or (name == "lab-admins" and config.get("admin", False))
                  or any(g["name"] == name and (not g.get("adminOnly", False) or config.get("admin", False)) for g in policy_groups))
        api.request("PUT" if member else "DELETE", user_path + "/groups/" + groups[0]["id"])
    # Renaming the Vaultwarden login disables previously managed identities.
    managed = api.request("GET", path + "?" + urllib.parse.urlencode({"q": marker + ":true", "max": "1000"}))
    for old in managed:
        if old["id"] != existing["id"] and old.get("attributes", {}).get(marker) == ["true"]:
            api.request("PUT", path + "/" + old["id"], {"enabled": False})
            api.request("POST", path + "/" + old["id"] + "/logout")
    return username


def publish_secret(kube, destination, credential_dir, identity=None):
    path = "/api/v1/namespaces/" + destination["namespace"] + "/secrets/" + destination.get("name", "sso-oidc")
    current = kube.request("GET", path)
    desired = {key: base64.b64encode(read_secret(credential_dir, source).encode()).decode()
               for key, source in destination["keys"].items()}
    for key, value in destination.get("literals", {}).items():
        desired[key] = base64.b64encode(value.encode()).decode()
    for key, source in destination.get("sha256", {}).items():
        value = hashlib.sha256(read_secret(credential_dir, source).encode()).hexdigest()
        desired[key] = base64.b64encode(value.encode()).decode()
    for key, source in destination.get("base64sha256", {}).items():
        value = base64.b64encode(hashlib.sha256(read_secret(credential_dir, source).encode()).digest())
        desired[key] = base64.b64encode(value).decode()
    if destination.get("adminEmails"):
        if identity is None:
            raise ReconcileError("Missing managed identity for admin roster")
        username, user = identity
        email = user.get("email") or (username if "@" in username else username + "@" + user["emailDomain"])
        roster = email + "\n" if user.get("admin", False) and user.get("enabled", True) else ""
        desired["admins"] = base64.b64encode(roster.encode()).decode()
    if any(current.get("data", {}).get(key) != value for key, value in desired.items()):
        kube.request("PATCH", path,
                     {"metadata": {"resourceVersion": current["metadata"]["resourceVersion"]}, "data": desired},
                     content_type="application/merge-patch+json")


def configure_openshift(kube, settings, username):
    # Validate the public HTTPS discovery endpoint before modifying cluster login.
    discovery = API(settings["issuer"]).request("GET", "/.well-known/openid-configuration")
    if discovery.get("issuer") != settings["issuer"]:
        raise ReconcileError("Public OIDC discovery returned an unexpected issuer")
    path = "/apis/config.openshift.io/v1/oauths/cluster"
    oauth = kube.request("GET", path)
    provider = {
        "name": "lab-sso", "type": "OpenID", "mappingMethod": "claim",
        "openID": {"issuer": settings["issuer"], "clientID": "openshift",
                   "clientSecret": {"name": "sso-oidc"},
                   "extraScopes": ["profile", "email"],
                   "claims": {"preferredUsername": ["preferred_username"],
                              "name": ["name"], "email": ["email"]}},
    }
    providers = oauth.get("spec", {}).get("identityProviders", [])
    desired = [p for p in providers if p["name"] != "lab-sso"] + [provider]
    if providers != desired:
        # resourceVersion prevents overwriting a concurrent provider change.
        kube.request("PATCH", path,
                     {"metadata": {"resourceVersion": oauth["metadata"]["resourceVersion"]},
                      "spec": {"identityProviders": desired}},
                     content_type="application/merge-patch+json")
    # OpenShift does not persist OIDC group claims as Group objects.
    for name in ["lab-users", "lab-admins"]:
        path = "/apis/user.openshift.io/v1/groups/" + name
        group = kube.request("GET", path)
        desired_users = [username] if settings["user"].get("enabled", True) and (name == "lab-users" or settings["user"].get("admin", False)) else []
        if (group.get("users") or []) != desired_users:
            kube.request("PATCH", path,
                         {"metadata": {"resourceVersion": group["metadata"]["resourceVersion"]}, "users": desired_users},
                         content_type="application/merge-patch+json")


def main():
    settings = json.loads(Path("/config/settings.json").read_text())
    admin_password = read_secret("/credentials/admin", "password")
    api = API(os.environ.get("KEYCLOAK_URL", "http://keycloak.sso.svc:8080"))
    token = api.request("POST", "/realms/master/protocol/openid-connect/token", form={
        "client_id": "admin-cli", "grant_type": "password",
        "username": "bootstrap-admin", "password": admin_password,
    })
    api.token = token["access_token"]
    realm = "/admin/realms/" + urllib.parse.quote(settings["realm"], safe="")
    if api.request("GET", realm, missing=True) is None:
        api.request("POST", "/admin/realms", {"realm": settings["realm"], "enabled": True})
    api.request("PUT", realm, {
        "enabled": True, "registrationAllowed": False, "resetPasswordAllowed": False,
        "rememberMe": True, "bruteForceProtected": True, "sslRequired": "external",
    })
    sa = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    kube = API("https://kubernetes.default.svc", read_secret(sa, "token"), str(sa / "ca.crt"))
    for definition in settings["clients"]:
        client = dict(definition)
        remote = client.pop("remoteSecret", None)
        supplied_secret = None
        if remote:
            secret = kube.request("GET", "/api/v1/namespaces/" + remote["namespace"] + "/secrets/" + remote["name"], missing=remote.get("optional", False))
            if secret is None:
                print("Optional SSO application credential absent; client registration deferred.")
                continue
            supplied_secret = base64.b64decode(secret["data"][remote["key"]], validate=True).decode()
            if not supplied_secret:
                raise ReconcileError("An application OIDC credential is empty")
        upsert_client(api, realm, client, "/credentials/clients", supplied_secret)
    profile = api.request("GET", realm + "/users/profile")
    names = {a["name"] for a in profile.get("attributes", [])}
    for name in ["lab-sso-managed", "lab-sso-password-version"]:
        if name not in names:
            profile.setdefault("attributes", []).append({
                "name": name, "multivalued": False,
                "permissions": {"view": ["admin"], "edit": ["admin"]},
            })
    if names != {a["name"] for a in profile["attributes"]}:
        api.request("PUT", realm + "/users/profile", profile)
    username = reconcile_user(api, realm, settings["user"], admin_password, "/credentials/user")
    sa = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    kube = API("https://kubernetes.default.svc", read_secret(sa, "token"), str(sa / "ca.crt"))
    for destination in settings.get("secretDestinations", []):
        publish_secret(kube, destination, "/credentials/clients", (username, settings["user"]))
    if settings.get("openshift"):
        configure_openshift(kube, settings, username)
    print("SSO realm, account, groups, and application clients reconciled.")


if __name__ == "__main__":
    try:
        main()
    except (ReconcileError, KeyError, ValueError, OSError) as error:
        # Unexpected JSON or filesystem errors can contain secret contents.
        print(str(error) if isinstance(error, ReconcileError) else "Invalid SSO settings, API response, or mounted credentials", file=sys.stderr)
        sys.exit(1)
