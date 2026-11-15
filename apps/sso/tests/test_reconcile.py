"""Credential lifecycle and shared OpenShift OAuth regression checks."""

import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

spec = importlib.util.spec_from_file_location("reconcile", Path(__file__).resolve().parents[1] / "reconcile.py")
reconcile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconcile)


class IdentityAPI:
    def __init__(self):
        self.users = {}
        self.groups = {"lab-users": "users", "lab-admins": "admins"}
        self.resets = []
        self.logouts = []
        self.memberships = set()
        self.initial_passwords = []

    def request(self, method, path, body=None, **kwargs):
        url = urlsplit(path)
        query = parse_qs(url.query)
        parts = url.path.strip("/").split("/")
        if parts[-1] == "users" and method == "GET":
            if "username" in query:
                return [u for u in self.users.values() if u["username"] == query["username"][0]]
            return [u for u in self.users.values() if u.get("attributes", {}).get("lab-sso-managed") == ["true"]]
        if parts[-1] == "users" and method == "POST":
            user = json.loads(json.dumps(body))
            self.initial_passwords.append(user.pop("credentials")[0]["value"])
            user["id"] = str(len(self.users) + 1)
            self.users[user["id"]] = user
            return
        if parts[-1] == "groups" and method == "GET":
            return [{"name": query["search"][0], "id": self.groups[query["search"][0]]}]
        uid = parts[parts.index("users") + 1]
        if parts[-1] == "reset-password":
            self.resets.append((uid, body["value"]))
        elif parts[-1] == "logout":
            self.logouts.append(uid)
        elif "groups" in parts:
            pair = (uid, parts[-1])
            if method == "PUT":
                self.memberships.add(pair)
            else:
                self.memberships.discard(pair)
        elif method == "PUT":
            self.users[uid].update(json.loads(json.dumps(body)))
        else:
            raise AssertionError((method, path))


class IdentityLifecycle(unittest.TestCase):
    def setUp(self):
        self.api = IdentityAPI()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.username = "lab.person"
        self.password = 'spaces, "quotes", $symbols, and a newline\n'
        self.config = {"emailDomain": "example.test", "admin": False}

    def run_sync(self):
        (self.directory / "username").write_text(self.username)
        (self.directory / "password").write_text(self.password)
        return reconcile.reconcile_user(self.api, "/admin/realms/lab", self.config, "separate-admin-secret", self.directory)

    def test_creates_exact_vaultwarden_login_with_read_only_membership(self):
        self.assertEqual(self.run_sync(), self.username)
        self.assertEqual(self.api.initial_passwords, [self.password])
        self.assertEqual(self.api.users["1"]["username"], self.username)
        self.assertEqual(self.api.memberships, {("1", "users")})
        self.assertNotIn(self.password, json.dumps(self.api.users))

    def test_unchanged_password_is_not_reset(self):
        self.run_sync()
        self.run_sync()
        self.assertEqual(self.api.resets, [])
        self.assertEqual(self.api.logouts, [])

    def test_rotation_resets_once_and_invalidates_sessions(self):
        self.run_sync()
        self.password = "replacement-password"
        self.run_sync()
        self.run_sync()
        self.assertEqual(self.api.resets, [("1", self.password)])
        self.assertEqual(self.api.logouts, ["1"])

    def test_rename_disables_and_logs_out_previous_identity(self):
        self.run_sync()
        self.username = "new.person"
        self.run_sync()
        self.assertFalse(self.api.users["1"]["enabled"])
        self.assertTrue(self.api.users["2"]["enabled"])
        self.assertIn("1", self.api.logouts)

    def test_unmanaged_existing_account_is_not_taken_over(self):
        self.api.users["existing"] = {"id": "existing", "username": self.username}
        with self.assertRaises(reconcile.ReconcileError):
            self.run_sync()
        self.assertEqual(self.api.resets, [])
        self.assertEqual(self.api.initial_passwords, [])

    def test_admin_access_requires_explicit_setting_and_can_be_removed(self):
        self.run_sync()
        self.config["admin"] = True
        self.run_sync()
        self.assertIn(("1", "admins"), self.api.memberships)
        self.config["admin"] = False
        self.run_sync()
        self.assertNotIn(("1", "admins"), self.api.memberships)


class OpenShiftIntegration(unittest.TestCase):
    def test_preserves_recovery_provider_and_uses_resource_version(self):
        recovery = {"name": "recovery", "type": "HTPasswd", "htpasswd": {"fileData": {"name": "recovery"}}}
        patches = []

        class Kube:
            def request(self, method, path, body=None, **kwargs):
                if method == "PATCH":
                    patches.append((path, body))
                    return
                if "/oauths/" in path:
                    return {"metadata": {"resourceVersion": "42"}, "spec": {"identityProviders": [recovery]}}
                return {"metadata": {"resourceVersion": "43"}, "users": []}

        settings = {"issuer": "https://sso.example.test/realms/lab", "user": {"admin": False}}
        with patch.object(reconcile.API, "request", return_value={"issuer": settings["issuer"]}):
            reconcile.configure_openshift(Kube(), settings, "lab.person")
        oauth_patch = next(body for path, body in patches if "/oauths/" in path)
        self.assertEqual(oauth_patch["metadata"]["resourceVersion"], "42")
        self.assertEqual(oauth_patch["spec"]["identityProviders"][0], recovery)
        self.assertEqual(oauth_patch["spec"]["identityProviders"][1]["name"], "lab-sso")

    def test_invalid_public_discovery_prevents_cluster_login_changes(self):
        class Kube:
            def request(self, *args, **kwargs):
                raise AssertionError("Cluster API must not be changed")

        settings = {"issuer": "https://sso.example.test/realms/lab", "user": {}}
        with patch.object(reconcile.API, "request", return_value={"issuer": "https://wrong.example.test"}):
            with self.assertRaises(reconcile.ReconcileError):
                reconcile.configure_openshift(Kube(), settings, "lab.person")


class SecretPublication(unittest.TestCase):
    def test_unchanged_client_credentials_do_not_patch_or_roll_workloads(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "client").write_text("generated-client-secret")
            data = {"client-secret": base64.b64encode(b"generated-client-secret").decode()}
            class Kube:
                def request(self, method, *args, **kwargs):
                    if method != "GET":
                        raise AssertionError("Unchanged credential should not be patched")
                    return {"data": data}
            reconcile.publish_secret(Kube(), {"namespace": "app", "keys": {"client-secret": "client"}}, directory)


if __name__ == "__main__":
    unittest.main()
