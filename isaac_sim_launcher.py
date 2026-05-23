"""
Isaac Sim Launcher GUI
======================
Automates SSH connection, Docker container management, port-forwarding,
and readiness monitoring for NVIDIA Isaac Sim.

Requirements: pip install paramiko
Usage:        python isaac_sim_launcher.py
"""

import tkinter as tk
from tkinter import ttk, messagebox
import paramiko
import threading
import json
import os
import time
import socket
import select
from cryptography.fernet import Fernet, InvalidToken

SSH_HOST = "10.158.244.8"
CREDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "isaac_sim_creds.json")
KEY_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".isaac_sim.key")

DOCKER_RUN_CMD = (
    'docker run --name isaac-sim '
    '--entrypoint bash '
    '-it '
    '--rm '
    '--gpus all '
    '--network=host '
    '-e "ACCEPT_EULA=Y" '
    '-e "PRIVACY_CONSENT=Y" '
    '-v ~/docker/isaac-sim/cache/main:/isaac-sim/.cache:rw '
    '-v ~/docker/isaac-sim/cache/computecache:/isaac-sim/.nv/ComputeCache:rw '
    '-v ~/docker/isaac-sim/logs:/isaac-sim/.nvidia-omniverse/logs:rw '
    '-v ~/docker/isaac-sim/config:/isaac-sim/.nvidia-omniverse/config:rw '
    '-v ~/docker/isaac-sim/data:/isaac-sim/.local/share/ov/data:rw '
    '-v ~/docker/isaac-sim/pkg:/isaac-sim/.local/share/ov/pkg:rw '
    '-v /srv/shared/frrobot_isaacsim_model:'
    '/isaac-sim/.local/share/ov/pkg/urdf/frrobot:rw '
    '-v /srv/shared/dh_gripper_ros:'
    '/isaac-sim/.local/share/ov/pkg/urdf/dh_gripper:rw '
    '-u 1234:1234 '
    'nvcr.io/nvidia/isaac-sim:5.1.0'
)

# ── Color palette (Catppuccin Mocha) ──────────────────────────
BG      = "#1e1e2e"
BG2     = "#313244"
BG3     = "#181825"
FG      = "#cdd6f4"
SUBTLE  = "#a6adc8"
MUTED   = "#6c7086"
BLUE    = "#89b4fa"
GREEN   = "#a6e3a1"
YELLOW  = "#f9e2af"
RED     = "#f38ba8"
PEACH   = "#fab387"
TEAL    = "#94e2d5"


# ═══════════════════════════════════════════════════════════════
#  Port-forwarding helpers
# ═══════════════════════════════════════════════════════════════
def _tunnel_handler(chan, sock):
    """Bi-directional data shuttle between an SSH channel and a local socket."""
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
    """Accept local connections and forward them through the SSH transport."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.settimeout(1.0)
    try:
        srv.bind(("127.0.0.1", local_port))
    except OSError as e:
        # Port already in use — not fatal, just skip
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


# ═══════════════════════════════════════════════════════════════
#  Main application
# ═══════════════════════════════════════════════════════════════
class IsaacSimLauncher:

    def __init__(self, root):
        self.root = root
        self.root.title("Isaac Sim Launcher")
        self.root.geometry("760x560")
        self.root.configure(bg=BG)
        self.root.minsize(600, 400)

        self.ssh_cmd = None          # paramiko client – commands
        self.ssh_tun = None          # paramiko client – tunnels
        self.shell = None
        self.is_running = False
        self.is_ready = False
        self.stop_event = threading.Event()

        saved = self._load_creds()
        self._show_login(saved)

    # ── credentials (Fernet-encrypted at rest) ─────────────────
    @staticmethod
    def _get_or_create_key():
        """Return the Fernet key, creating one on first use."""
        if os.path.exists(KEY_FILE):
            with open(KEY_FILE, "rb") as f:
                return f.read()
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        # Try to hide the key file on Windows
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(KEY_FILE, 0x02)
        except Exception:
            pass
        return key

    @staticmethod
    def _load_creds():
        if not os.path.exists(CREDS_FILE) or not os.path.exists(KEY_FILE):
            return {}
        try:
            with open(KEY_FILE, "rb") as f:
                key = f.read()
            fernet = Fernet(key)
            with open(CREDS_FILE, "r") as f:
                data = json.load(f)
            decrypted_pw = fernet.decrypt(
                data["password"].encode()).decode()
            return {"username": data["username"],
                    "password": decrypted_pw}
        except (InvalidToken, KeyError, Exception):
            # Corrupted or mismatched key — start fresh
            return {}

    @staticmethod
    def _save_creds(user, pw):
        key = IsaacSimLauncher._get_or_create_key()
        fernet = Fernet(key)
        encrypted_pw = fernet.encrypt(pw.encode()).decode()
        with open(CREDS_FILE, "w") as f:
            json.dump({"username": user,
                       "password": encrypted_pw}, f)

    # ── login dialog ──────────────────────────────────────────
    def _show_login(self, saved):
        self.root.withdraw()
        dlg = tk.Toplevel()
        dlg.title("SSH Credentials")
        dlg.geometry("370x240")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW",
                      lambda: (dlg.destroy(), self.root.destroy()))

        tk.Label(dlg, text="Isaac Sim Launcher",
                 font=("Segoe UI", 16, "bold"),
                 bg=BG, fg=FG).pack(pady=(18, 2))
        tk.Label(dlg, text=f"SSH → {SSH_HOST}",
                 font=("Segoe UI", 10),
                 bg=BG, fg=SUBTLE).pack(pady=(0, 12))

        frm = tk.Frame(dlg, bg=BG)
        frm.pack(padx=30, fill="x")
        frm.columnconfigure(1, weight=1)

        tk.Label(frm, text="Username:", font=("Segoe UI", 10),
                 bg=BG, fg=FG).grid(row=0, column=0, sticky="w", pady=4)
        e_user = tk.Entry(frm, font=("Segoe UI", 10), bg=BG2, fg=FG,
                          insertbackground=FG, relief="flat", bd=5)
        e_user.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)

        tk.Label(frm, text="Password:", font=("Segoe UI", 10),
                 bg=BG, fg=FG).grid(row=1, column=0, sticky="w", pady=4)
        e_pass = tk.Entry(frm, font=("Segoe UI", 10), bg=BG2, fg=FG,
                          insertbackground=FG, relief="flat", bd=5, show="•")
        e_pass.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=4)

        if saved:
            e_user.insert(0, saved.get("username", ""))
            e_pass.insert(0, saved.get("password", ""))

        remember = tk.BooleanVar(value=bool(saved))
        tk.Checkbutton(dlg, text="Remember credentials", variable=remember,
                       font=("Segoe UI", 9), bg=BG, fg=SUBTLE,
                       selectcolor=BG2, activebackground=BG).pack(pady=(8, 4))

        def submit():
            u, p = e_user.get().strip(), e_pass.get().strip()
            if not u or not p:
                messagebox.showwarning("Missing",
                                       "Enter both username and password.")
                return
            self.username, self.password = u, p
            if remember.get():
                self._save_creds(u, p)
            dlg.destroy()
            self.root.deiconify()
            self._build_ui()

        tk.Button(dlg, text="Connect", font=("Segoe UI", 11, "bold"),
                  bg=BLUE, fg=BG, relief="flat", activebackground=TEAL,
                  cursor="hand2", command=submit
                  ).pack(pady=(8, 16), ipadx=20, ipady=4)
        e_pass.bind("<Return>", lambda _: submit())
        dlg.focus_force()
        e_user.focus_set()

    # ── main UI ───────────────────────────────────────────────
    def _build_ui(self):
        # header row
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(hdr, text="NVIDIA Isaac Sim Launcher",
                 font=("Segoe UI", 17, "bold"),
                 bg=BG, fg=FG).pack(side="left")

        # status indicator (right side of header)
        sf = tk.Frame(hdr, bg=BG)
        sf.pack(side="right")
        self.dot = tk.Canvas(sf, width=14, height=14,
                             bg=BG, highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 5))
        self.dot.create_oval(2, 2, 12, 12, fill=MUTED, outline="", tags="d")
        self.status_lbl = tk.Label(sf, text="Not Started",
                                   font=("Segoe UI", 10), bg=BG, fg=MUTED)
        self.status_lbl.pack(side="left")

        # info bar
        bar = tk.Frame(self.root, bg=BG2)
        bar.pack(fill="x", padx=20, pady=(4, 8))
        tk.Label(bar,
                 text=f"  Host: {SSH_HOST}  │  User: {self.username}",
                 font=("Segoe UI", 9), bg=BG2, fg=SUBTLE
                 ).pack(side="left", pady=4)

        # button row
        btn_row = tk.Frame(self.root, bg=BG)
        btn_row.pack(padx=20, pady=(4, 8), fill="x")

        self.run_btn = tk.Button(
            btn_row, text="▶   Run Isaac Sim",
            font=("Segoe UI", 13, "bold"),
            bg=GREEN, fg=BG, relief="flat",
            activebackground=TEAL, cursor="hand2",
            command=self._on_run)
        self.run_btn.pack(side="left", fill="x", expand=True, ipady=7)

        self.stop_btn = tk.Button(
            btn_row, text="■   Stop",
            font=("Segoe UI", 13, "bold"),
            bg=RED, fg=BG, relief="flat",
            activebackground="#eba0ac", cursor="hand2",
            command=self._on_stop)
        self.stop_btn.pack(side="right", fill="x", expand=True,
                           ipady=7, padx=(8, 0))
        self.stop_btn.configure(state="disabled")

        # ── Managed Instances panel (additive — does not affect the Run/Stop flow) ──
        self._instances_data   = []   # list of dicts from backend.list_instances
        self._inst_ssh         = None
        self._inst_tunnel_stop = None

        inst_frame = tk.Frame(self.root, bg=BG2)
        inst_frame.pack(fill="x", padx=20, pady=(0, 6))

        hdr2 = tk.Frame(inst_frame, bg=BG2)
        hdr2.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(hdr2, text="Managed Instances",
                 font=("Segoe UI", 10, "bold"),
                 bg=BG2, fg=SUBTLE).pack(side="left")
        tk.Label(hdr2,
                 text="(from Isaac-Sim-Manager on server — independent of Run button above)",
                 font=("Segoe UI", 8), bg=BG2, fg=MUTED).pack(side="left", padx=6)

        inst_body = tk.Frame(inst_frame, bg=BG2)
        inst_body.pack(fill="x", padx=8, pady=(0, 6))

        lb_frame = tk.Frame(inst_body, bg=BG2)
        lb_frame.pack(side="left", fill="both", expand=True)
        self._inst_lb = tk.Listbox(
            lb_frame,
            height=4,
            font=("Consolas", 9),
            bg=BG3, fg=FG,
            selectbackground=BLUE, selectforeground=BG,
            relief="flat", bd=4,
            activestyle="none",
        )
        inst_sb = ttk.Scrollbar(lb_frame, command=self._inst_lb.yview)
        self._inst_lb.configure(yscrollcommand=inst_sb.set)
        inst_sb.pack(side="right", fill="y")
        self._inst_lb.pack(fill="both", expand=True)

        btn2 = tk.Frame(inst_body, bg=BG2)
        btn2.pack(side="right", padx=(8, 0), fill="y")
        for label, cmd, clr in [
            ("↺ Refresh",  self._inst_refresh,  BLUE),
            ("⚡ Connect",  self._inst_connect,  TEAL),
            ("▶ Start",    self._inst_start,    GREEN),
            ("■ Stop",     self._inst_stop,     RED),
        ]:
            tk.Button(btn2, text=label,
                      font=("Segoe UI", 9, "bold"),
                      bg=clr, fg=BG, relief="flat",
                      activebackground=YELLOW, cursor="hand2",
                      command=cmd
                      ).pack(fill="x", pady=2, ipady=2)

        self._inst_status = tk.Label(
            inst_frame, text="  Click ↺ Refresh to load instances",
            font=("Segoe UI", 8), bg=BG2, fg=MUTED, anchor="w")
        self._inst_status.pack(fill="x", padx=8, pady=(0, 4))

        # log area
        lf = tk.Frame(self.root, bg=BG)
        lf.pack(fill="both", expand=True, padx=20, pady=(0, 14))
        tk.Label(lf, text="Output Log",
                 font=("Segoe UI", 10, "bold"),
                 bg=BG, fg=SUBTLE).pack(anchor="w", pady=(0, 4))

        self.log = tk.Text(lf, font=("Consolas", 9), bg=BG3, fg=FG,
                           insertbackground=FG, relief="flat", bd=8,
                           wrap="word", state="disabled")
        sb = ttk.Scrollbar(lf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)

        for tag, color in [("info", BLUE), ("ok", GREEN),
                           ("err", RED), ("cmd", PEACH)]:
            self.log.tag_configure(tag, foreground=color)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Managed Instances helpers ─────────────────────────────

    def _inst_set_status(self, text, color=None):
        def _do():
            self._inst_status.configure(
                text=f"  {text}",
                fg=color or MUTED)
        self.root.after(0, _do)

    def _inst_get_or_connect_ssh(self):
        """Return a live SSH client for instance management, reconnecting if needed."""
        try:
            if self._inst_ssh and self._inst_ssh.get_transport() and \
                    self._inst_ssh.get_transport().is_active():
                return self._inst_ssh
        except Exception:
            pass
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(SSH_HOST, username=self.username,
                       password=self.password, timeout=15)
        self._inst_ssh = client
        return client

    def _inst_refresh(self):
        def _worker():
            try:
                from backend import list_instances
                ssh = self._inst_get_or_connect_ssh()
                instances = list_instances(ssh)
                self._instances_data = instances

                def _update():
                    self._inst_lb.delete(0, "end")
                    if not instances:
                        self._inst_lb.insert("end", "  (no containers found)")
                    for inst in instances:
                        state = inst["state"].upper()
                        tag   = "(legacy)" if inst["is_legacy"] else ""
                        line  = f"  {inst['name']:<28} {state:<10} {tag}"
                        self._inst_lb.insert("end", line)
                    self._inst_set_status(
                        f"{len(instances)} container(s) found — "
                        f"{sum(1 for i in instances if i['state'].lower()=='running')} running",
                        SUBTLE)
                self.root.after(0, _update)
            except Exception as e:
                self._inst_set_status(f"Refresh failed: {e}", RED)

        threading.Thread(target=_worker, daemon=True).start()
        self._inst_set_status("Refreshing…", YELLOW)

    def _inst_selected(self):
        idx = self._inst_lb.curselection()
        if not idx or not self._instances_data:
            return None
        i = idx[0]
        return self._instances_data[i] if i < len(self._instances_data) else None

    def _inst_connect(self):
        inst = self._inst_selected()
        if not inst:
            self._inst_set_status("Select an instance first", YELLOW)
            return
        if inst["state"].lower() != "running":
            self._inst_set_status("Instance is not running — start it first", RED)
            return

        def _worker():
            try:
                from backend import run_tunnel_server
                # Close existing managed-instance tunnels
                if self._inst_tunnel_stop:
                    self._inst_tunnel_stop.set()
                stop_evt  = threading.Event()
                self._inst_tunnel_stop = stop_evt

                ssh_tun = paramiko.SSHClient()
                ssh_tun.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh_tun.connect(SSH_HOST, username=self.username,
                                password=self.password, timeout=15)
                transport = ssh_tun.get_transport()

                rest_port   = inst["rest_port"]
                webrtc_port = inst["webrtc_port"]
                for lp, rp in ((rest_port, rest_port), (webrtc_port, webrtc_port)):
                    threading.Thread(
                        target=run_tunnel_server,
                        args=(lp, rp, transport, stop_evt),
                        daemon=True
                    ).start()

                self._inst_set_status(
                    f"Tunnels active → localhost:{rest_port} (REST)  "
                    f"localhost:{webrtc_port} (WebRTC)  —  {inst['name']}",
                    GREEN)
                self._print(
                    f"\n⚡ Connected to {inst['name']}  "
                    f"(REST ::{rest_port}  WebRTC ::{webrtc_port})", "ok")
            except Exception as e:
                self._inst_set_status(f"Tunnel error: {e}", RED)

        threading.Thread(target=_worker, daemon=True).start()
        self._inst_set_status(f"Setting up tunnels to {inst['name']}…", YELLOW)

    def _inst_start(self):
        inst = self._inst_selected()
        if not inst:
            self._inst_set_status("Select an instance first", YELLOW)
            return

        def _worker():
            try:
                from backend import start_container, start_managed_instance
                ssh = self._inst_get_or_connect_ssh()
                if inst["is_managed"] or inst["is_legacy"]:
                    start_container(ssh, inst["name"])
                else:
                    start_managed_instance(
                        ssh, inst["name"].removeprefix("isaac-sim-"))
                self._inst_set_status(f"Started {inst['name']}", GREEN)
                self._inst_refresh()
            except Exception as e:
                self._inst_set_status(f"Start failed: {e}", RED)

        threading.Thread(target=_worker, daemon=True).start()
        self._inst_set_status(f"Starting {inst['name']}…", YELLOW)

    def _inst_stop(self):
        inst = self._inst_selected()
        if not inst:
            self._inst_set_status("Select an instance first", YELLOW)
            return

        def _worker():
            try:
                from backend import stop_container
                ssh = self._inst_get_or_connect_ssh()
                stop_container(ssh, inst["name"])
                self._inst_set_status(f"Stopped {inst['name']}", SUBTLE)
                self._inst_refresh()
            except Exception as e:
                self._inst_set_status(f"Stop failed: {e}", RED)

        threading.Thread(target=_worker, daemon=True).start()
        self._inst_set_status(f"Stopping {inst['name']}…", YELLOW)

    # ── helpers ───────────────────────────────────────────────
    def _print(self, msg, tag=""):
        def _do():
            self.log.configure(state="normal")
            self.log.insert("end", msg + "\n", tag)
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, _do)

    def _status(self, text, color):
        def _do():
            self.status_lbl.configure(text=text, fg=color)
            self.dot.itemconfigure("d", fill=color)
        self.root.after(0, _do)

    def _drain(self):
        """Read and log any buffered shell output."""
        out = ""
        while self.shell and self.shell.recv_ready():
            out += self.shell.recv(8192).decode("utf-8", errors="replace")
        for line in out.splitlines():
            stripped = line.strip()
            if stripped:
                self._print(stripped)
        return out

    def _set_buttons(self, run_state, stop_state):
        """Thread-safe button state update."""
        def _do():
            if run_state == "running":
                self.run_btn.configure(state="disabled", bg=MUTED,
                                       text="⟳  Running…", cursor="arrow")
            elif run_state == "normal":
                self.run_btn.configure(state="normal", bg=GREEN,
                                       text="▶   Run Isaac Sim",
                                       cursor="hand2")
            if stop_state == "normal":
                self.stop_btn.configure(state="normal")
            elif stop_state == "disabled":
                self.stop_btn.configure(state="disabled")
        self.root.after(0, _do)

    # ── check readiness via remote curl over SSH ──────────────
    def _check_ready_remote(self):
        """Run curl on the *remote* machine via SSH — avoids tunnel issues."""
        try:
            if self.ssh_tun is None or not self.ssh_tun.get_transport():
                return False
            transport = self.ssh_tun.get_transport()
            if not transport.is_active():
                return False
            _, stdout, _ = self.ssh_tun.exec_command(
                "curl -s -o /dev/null -w '%{http_code}' "
                "http://localhost:8011/v1/streaming/ready",
                timeout=5)
            code = stdout.read().decode().strip().strip("'\"")
            return code == "200"
        except Exception:
            return False

    # ── run pipeline ──────────────────────────────────────────
    def _on_run(self):
        if self.is_running:
            return
        self.is_running = True
        self.is_ready = False
        self.stop_event.clear()
        self._set_buttons("running", "normal")
        threading.Thread(target=self._pipeline, daemon=True).start()

    def _pipeline(self):
        try:
            # ── 1. SSH connect ────────────────────────────────
            self._status("Connecting…", YELLOW)
            self._print("Establishing SSH connection…", "info")

            self.ssh_cmd = paramiko.SSHClient()
            self.ssh_cmd.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_cmd.connect(SSH_HOST, username=self.username,
                                password=self.password, timeout=15)
            self._print(f"✓ Connected to {SSH_HOST}", "ok")

            self.shell = self.ssh_cmd.invoke_shell(width=200, height=50)
            time.sleep(1)
            self._drain()

            # ── 2. docker stop ────────────────────────────────
            self._status("Stopping old container…", YELLOW)
            self._print("\n$ docker stop isaac-sim", "cmd")
            self.shell.send("docker stop isaac-sim 2>/dev/null; "
                            "echo '__STOP_DONE__'\n")
            self._wait_for_marker("__STOP_DONE__", timeout=15)
            self._print("✓ Stop command complete", "ok")

            if self.stop_event.is_set():
                return

            # ── 3. docker rm ──────────────────────────────────
            self._status("Removing old container…", YELLOW)
            self._print("\n$ docker rm isaac-sim", "cmd")
            self.shell.send("docker rm isaac-sim 2>/dev/null; "
                            "echo '__RM_DONE__'\n")
            self._wait_for_marker("__RM_DONE__", timeout=10)
            self._print("✓ Remove command complete", "ok")

            if self.stop_event.is_set():
                return

            # ── 4. docker run ─────────────────────────────────
            self._status("Starting container…", YELLOW)
            self._print("\n$ docker run --name isaac-sim …", "cmd")
            self.shell.send(DOCKER_RUN_CMD + "\n")
            time.sleep(8)
            self._drain()
            self._print("✓ Container starting", "ok")

            if self.stop_event.is_set():
                return

            # ── 5. run headless script inside container ───────
            self._status("Launching headless…", YELLOW)
            self._print("\n$ ./runheadless.sh -v", "cmd")
            self.shell.send("./runheadless.sh -v\n")
            time.sleep(3)
            self._drain()
            self._print("✓ Headless script launched", "ok")

            if self.stop_event.is_set():
                return

            # ── 6. set up second SSH + tunnels ────────────────
            self._print("\nOpening tunnel SSH connection…", "info")
            self.ssh_tun = paramiko.SSHClient()
            self.ssh_tun.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_tun.connect(SSH_HOST, username=self.username,
                                password=self.password, timeout=15)
            transport = self.ssh_tun.get_transport()

            self._print("Starting port forwards (8011, 49100)…", "info")
            for port in (8011, 49100):
                t = threading.Thread(target=run_tunnel_server,
                                     args=(port, port, transport,
                                           self.stop_event),
                                     daemon=True)
                t.start()
            self._print("✓ Tunnels active  →  localhost:8011, "
                        "localhost:49100", "ok")

            # ── 7. poll readiness via remote curl ─────────────
            self._status("Waiting for readiness…", YELLOW)
            self._print("\nPolling readiness on remote host "
                        "(curl localhost:8011/v1/streaming/ready)…", "info")

            for attempt in range(180):       # up to ~15 minutes
                if self.stop_event.is_set():
                    return

                # keep draining shell output so user sees logs
                self._drain()

                ready = self._check_ready_remote()

                if ready:
                    self.is_ready = True
                    self._status("✓  READY", GREEN)
                    self._print("")
                    self._print("══════════════════════════════════"
                                "══════════", "ok")
                    self._print("   Isaac Sim is READY!", "ok")
                    self._print("   Stream → http://localhost:8011", "ok")
                    self._print("══════════════════════════════════"
                                "══════════", "ok")
                    # keep draining output in background while ready
                    self._background_drain()
                    return

                self._print(f"  [{attempt + 1}] Not ready yet…")
                time.sleep(5)

            # timed out
            self._status("Timed out", RED)
            self._print("\n⚠ Readiness check timed out after ~15 min.", "err")

        except paramiko.AuthenticationException:
            self._status("Auth failed", RED)
            self._print("✗ SSH authentication failed — "
                        "check your credentials.", "err")
        except Exception as exc:
            self._status("Error", RED)
            self._print(f"✗ {exc}", "err")
        finally:
            if not self.is_ready:
                self.is_running = False
                self._set_buttons("normal", "disabled")

    def _wait_for_marker(self, marker, timeout=15):
        """Block until `marker` appears in shell output or timeout."""
        end = time.time() + timeout
        buf = ""
        while time.time() < end and not self.stop_event.is_set():
            if self.shell.recv_ready():
                chunk = self.shell.recv(8192).decode("utf-8", errors="replace")
                buf += chunk
                for line in chunk.splitlines():
                    stripped = line.strip()
                    if stripped and marker not in stripped:
                        self._print(stripped)
                if marker in buf:
                    return
            time.sleep(0.3)

    def _background_drain(self):
        """Keep draining shell output while Isaac Sim is running."""
        def _loop():
            while not self.stop_event.is_set():
                try:
                    self._drain()
                except Exception:
                    break
                time.sleep(2)
        threading.Thread(target=_loop, daemon=True).start()

    # ── stop ──────────────────────────────────────────────────
    def _on_stop(self):
        if not self.is_running:
            return
        self._print("\n⏹ Stopping…", "err")
        self._status("Stopping…", RED)
        self.stop_event.set()
        threading.Thread(target=self._teardown, daemon=True).start()

    def _teardown(self):
        """Gracefully stop the container and close all connections."""
        # Try to stop the container on the remote host
        try:
            if self.ssh_cmd and self.ssh_cmd.get_transport():
                self._print("$ docker stop isaac-sim", "cmd")
                self.ssh_cmd.exec_command("docker stop isaac-sim",
                                         timeout=10)
                time.sleep(2)
        except Exception:
            pass

        # Close all SSH connections
        for client in (self.ssh_tun, self.ssh_cmd):
            if client:
                try:
                    client.close()
                except Exception:
                    pass
        self.ssh_cmd = None
        self.ssh_tun = None
        self.shell = None

        self.is_running = False
        self.is_ready = False
        self._print("✓ All connections closed.\n", "ok")
        self._status("Stopped", MUTED)
        self._set_buttons("normal", "disabled")

    # ── window close ──────────────────────────────────────────
    def _on_close(self):
        self.stop_event.set()
        if self._inst_tunnel_stop:
            self._inst_tunnel_stop.set()
        for client in (self.ssh_cmd, self.ssh_tun, self._inst_ssh):
            if client:
                try:
                    client.close()
                except Exception:
                    pass
        self.root.destroy()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Isaac Sim Launcher")
    parser.add_argument("--tui", "-t", action="store_true",
                        help="Run as terminal TUI instead of GUI")
    args = parser.parse_args()

    if args.tui:
        # TUI mode — instance picker backed by backend.py
        # Import here so the GUI path never requires paramiko to be installed
        from tui import run_tui
        run_tui()
    else:
        root = tk.Tk()
        app = IsaacSimLauncher(root)
        root.mainloop()
