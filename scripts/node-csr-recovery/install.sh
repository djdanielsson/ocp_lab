#!/usr/bin/env bash
# Run on the workstation that should recover the lab after a shutdown.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export SCRIPT_DIR
export RECOVERY_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ocp-node-csr-recovery"
mkdir -p "$RECOVERY_DIR" "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
chmod 700 "$RECOVERY_DIR"
# Read the dedicated token directly into a private local file; never print it.
python3 - <<'PY'
import base64, json, os, pathlib, subprocess

def oc(*args):
    return json.loads(subprocess.check_output(['oc', *args, '-o', 'json']))

secret = oc('get', 'secret', 'node-csr-recovery-token', '-n', 'openshift-config')
cluster = json.loads(subprocess.check_output(['oc', 'config', 'view', '--minify', '--raw', '-o', 'json']))['clusters'][0]['cluster']
# Refuse to export credentials for a different API endpoint.
if cluster['server'] != 'https://api.ocp.lab.danielsson.us.com:6443':
    raise SystemExit('Unexpected cluster endpoint')
config = {
    'server': cluster['server'],
    'ca': base64.b64decode(secret['data']['ca.crt']).decode(),
    'token': base64.b64decode(secret['data']['token']).decode(),
}
path = pathlib.Path(os.environ['RECOVERY_DIR']) / 'credentials.json'
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.fchmod(fd, 0o600)
with os.fdopen(fd, 'w') as handle:
    json.dump(config, handle)
PY
# Verify dependencies and connectivity before enabling the timer.
/usr/bin/python3 "$SCRIPT_DIR/recover.py" --credentials "$RECOVERY_DIR/credentials.json"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
cat > "$UNIT_DIR/ocp-node-csr-recovery.service" <<EOF
[Unit]
Description=Validate and approve existing OCP lab node certificate requests

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 "$SCRIPT_DIR/recover.py" --credentials "$RECOVERY_DIR/credentials.json" --approve
TimeoutStartSec=120
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
RestrictSUIDSGID=yes
EOF
install -m 644 "$SCRIPT_DIR/ocp-node-csr-recovery.timer" "$UNIT_DIR/ocp-node-csr-recovery.timer"
systemctl --user daemon-reload
systemctl --user enable --now ocp-node-csr-recovery.timer
systemctl --user start ocp-node-csr-recovery.service
