"""
Shared SSH / Docker backend for both the GUI and TUI launchers.
The old launcher (isaac_sim_launcher.py) does NOT use this module —
it remains unchanged for backwards compatibility.
"""
import json
import os
import select
import socket
import threading
import time

import paramiko

SSH_HOST = "10.158.244.8"
IMAGE    = "nvcr.io/nvidia/isaac-sim:5.1.0"

MANAGED_PREFIX = "isaac-sim-"   # containers created by Isaac-Sim-Manager
LEGACY_NAME    = "isaac-sim"    # container created by the old launcher

VOLUMES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "volumes.json")


def create_volume(client, vol_name):
    """Create a named Docker volume on the remote host. Returns True on success."""
    _, _, code = run_cmd(client, f"docker volume create {vol_name}", timeout=10)
    return code == 0


def load_extra_mounts(inst_name):
    """Return list of {vital, source, dest} dicts for this instance from volumes.json."""
    try:
        with open(VOLUMES_FILE) as f:
            data = json.load(f)
        return list(data.get(inst_name, []))
    except Exception:
        return []


def save_extra_mounts(inst_name, mounts):
    """Persist extra mounts list for an instance to volumes.json. Returns True on success."""
    try:
        try:
            with open(VOLUMES_FILE) as f:
                data = json.load(f)
        except Exception:
            data = {}
        data[inst_name] = mounts
        with open(VOLUMES_FILE, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


# ── Port-forwarding (reused from original launcher) ───────────────────────────

def _tunnel_handler(chan, sock):
    try:
        while True:
            r, _, _ = select.select([chan, sock], [], [], 1.0)
            if chan in r:
                data = chan.recv(4096)
                if not data:
                    break
                sock.sendall(data)
            if sock in r:
                data = sock.recv(4096)
                if not data:
                    break
                chan.sendall(data)
    except Exception:
        pass
    finally:
        chan.close()
        sock.close()


def run_tunnel_server(local_port, remote_port, transport, stop_event):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.settimeout(1.0)
    try:
        srv.bind(("127.0.0.1", local_port))
    except OSError:
        return
    srv.listen(5)
    while not stop_event.is_set():
        try:
            client, addr = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            chan = transport.open_channel(
                "direct-tcpip", ("localhost", remote_port), addr)
        except Exception:
            client.close()
            continue
        threading.Thread(target=_tunnel_handler, args=(chan, client),
                         daemon=True).start()
    srv.close()


# ── SSH helpers ───────────────────────────────────────────────────────────────

def connect(host, username, password, timeout=15):
    """Return a connected paramiko SSHClient."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=username, password=password, timeout=timeout)
    return client


def run_cmd(client, cmd, timeout=15):
    """Run a command on the remote host and return (stdout, stderr, exit_code)."""
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out  = stdout.read().decode("utf-8", errors="replace")
    err  = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return out, err, code


# ── Instance discovery ────────────────────────────────────────────────────────

def list_instances(client):
    """
    Return a list of dicts describing all Isaac Sim containers on the remote host.
    Includes both managed containers (isaac-sim-*) and the legacy container (isaac-sim).
    Each dict: {name, state, ports, uptime, is_managed, is_legacy}
    """
    cmd = (
        f'docker ps -a --filter "ancestor={IMAGE}" '
        '--format "{{json .}}"'
    )
    out, _, _ = run_cmd(client, cmd)
    instances = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            c = json.loads(line)
        except json.JSONDecodeError:
            continue
        name     = c.get("Names", "").lstrip("/").split(",")[0]
        state    = c.get("State", "unknown")
        networks = c.get("Networks", "")
        ports_raw = c.get("Ports", "")
        uptime   = c.get("RunningFor", "")
        is_legacy  = (name == LEGACY_NAME)
        is_managed = name.startswith(MANAGED_PREFIX) and not is_legacy

        # Determine REST and WebRTC ports (host-net: always 8011/49100)
        if "host" in networks.lower():
            rest_port    = 8011
            webrtc_port  = 49100
            port_display = "host"
        else:
            rest_port    = _parse_host_port(ports_raw, 8011)
            webrtc_port  = _parse_host_port(ports_raw, 49100)
            port_display = ports_raw[:24] if ports_raw else "—"

        instances.append({
            "name":         name,
            "state":        state,
            "ports":        port_display,
            "rest_port":    rest_port,
            "webrtc_port":  webrtc_port,
            "uptime":       uptime,
            "is_managed":   is_managed,
            "is_legacy":    is_legacy,
        })
    return instances


def _parse_host_port(ports_str, container_port):
    """Extract the host-side port for a given container port from docker ps Ports string."""
    import re
    for host, cont in re.findall(r':(\d+)->(\d+)', ports_str):
        if int(cont) == container_port:
            return int(host)
    return container_port


# ── Container lifecycle ───────────────────────────────────────────────────────

def check_ready(client, rest_port=8011):
    """Return True if Isaac Sim streaming is ready on the remote host."""
    try:
        out, _, code = run_cmd(
            client,
            f"curl -s -o /dev/null -w '%{{http_code}}' "
            f"http://localhost:{rest_port}/v1/streaming/ready",
            timeout=5
        )
        return out.strip().strip("'\"") == "200"
    except Exception:
        return False


def stop_container(client, name, timeout=15):
    # SSH channel timeout must exceed the docker stop grace period
    run_cmd(client, f"docker stop --time {timeout} {name}", timeout=timeout + 20)


def start_container(client, name):
    run_cmd(client, f"docker start {name}", timeout=30)


def remove_container(client, name):
    # docker stop default grace period is 10s; give SSH channel 40s total
    run_cmd(client, f"docker stop {name} 2>/dev/null; docker rm {name}", timeout=40)


def start_managed_instance(client, short_name, srv_mounts=None):
    """
    Launch a new managed Isaac Sim container on the remote host.
    Uses the same docker run command as Isaac-Sim-Manager/manage.py.
    """
    inst_vols = [
        (f"isaac-sim-{short_name}-cache",  "/isaac-sim/.cache"),
        (f"isaac-sim-{short_name}-logs",   "/isaac-sim/.nvidia-omniverse/logs"),
        (f"isaac-sim-{short_name}-config", "/isaac-sim/.nvidia-omniverse/config"),
        (f"isaac-sim-{short_name}-data",   "/isaac-sim/.local/share/ov/data"),
        (f"isaac-sim-{short_name}-pkg",    "/isaac-sim/.local/share/ov/pkg"),
    ]
    shared_vol = "isaac-sim-computecache:/isaac-sim/.nv/ComputeCache:rw"

    vol_flags = " ".join(f"-v {v}:{p}:rw" for v, p in inst_vols)
    vol_flags += f" -v {shared_vol}"

    # Merge caller-supplied mounts with any saved in volumes.json
    cfg_mounts = load_extra_mounts(f"{MANAGED_PREFIX}{short_name}")
    combined   = list(srv_mounts) if srv_mounts else []
    for e in cfg_mounts:
        combined.append((e["source"], e["dest"]))

    for host_path, cpath in combined:
        vol_flags += f" -v {host_path}:{cpath}:rw"

    cmd = (
        f'docker run --name isaac-sim-{short_name} '
        '--detach --restart unless-stopped '
        '--gpus all --network host '
        '-e "ACCEPT_EULA=Y" -e "PRIVACY_CONSENT=Y" '
        f'{vol_flags} '
        '-u 1234:1234 '
        '--entrypoint /isaac-sim/runheadless.sh '
        f'{IMAGE} '
        '-v --/app/livestream/nvcf/quitOnSessionEnded=false'
    )
    _, err, code = run_cmd(client, cmd, timeout=30)
    return code == 0, err.strip()


def poll_ready(client, rest_port=8011, max_wait=900, interval=5,
               callback=None, stop_event=None):
    """
    Poll until ready or max_wait seconds elapse.
    callback(attempt, ready) called each cycle if provided.
    Returns True if ready, False if timed out or stopped.
    """
    for attempt in range(max_wait // interval):
        if stop_event and stop_event.is_set():
            return False
        ready = check_ready(client, rest_port)
        if callback:
            callback(attempt, ready)
        if ready:
            return True
        time.sleep(interval)
    return False
