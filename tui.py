#!/usr/bin/env python3
"""
Isaac Sim Launcher — TUI mode
Curses interface for listing, connecting to, and managing remote Isaac Sim instances.
"""
import curses
import json
import os
import re
import socket
import threading

import paramiko

from backend import (
    SSH_HOST, connect, run_cmd, list_instances, stop_container, start_container,
    remove_container, start_managed_instance, run_tunnel_server, check_ready,
)

SCRIPT_DIR   = os.path.dirname(os.path.realpath(__file__))
SERVERS_FILE = os.path.join(SCRIPT_DIR, "servers.json")

DEFAULT_SERVERS = [{"label": "GPU Server", "host": SSH_HOST}]

COL_NAME  = 2
COL_STAT  = 28
COL_PORTS = 46
COL_UP    = 64

# ── Colors ─────────────────────────────────────────────────────────────────────

def setup_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN,   -1)
    curses.init_pair(2, curses.COLOR_WHITE,  -1)
    curses.init_pair(3, curses.COLOR_GREEN,  -1)
    curses.init_pair(4, curses.COLOR_RED,    -1)
    curses.init_pair(5, curses.COLOR_BLACK,  curses.COLOR_CYAN)
    curses.init_pair(6, curses.COLOR_WHITE,  -1)
    curses.init_pair(7, curses.COLOR_YELLOW, -1)

C_TITLE = lambda: curses.color_pair(1) | curses.A_BOLD
C_HEAD  = lambda: curses.color_pair(2) | curses.A_BOLD
C_RUN   = lambda: curses.color_pair(3)
C_STOP  = lambda: curses.color_pair(4)
C_SEL   = lambda: curses.color_pair(5) | curses.A_BOLD
C_DIM   = lambda: curses.color_pair(6)
C_MSG   = lambda: curses.color_pair(7)

def safe(fn):
    try:
        fn()
    except curses.error:
        pass

def separator(scr, row, w):
    safe(lambda: scr.hline(row, 0, curses.ACS_HLINE, w))

def border(win, title=""):
    win.border(
        curses.ACS_VLINE, curses.ACS_VLINE,
        curses.ACS_HLINE, curses.ACS_HLINE,
        curses.ACS_ULCORNER, curses.ACS_URCORNER,
        curses.ACS_LLCORNER, curses.ACS_LRCORNER,
    )
    if title:
        safe(lambda: win.addstr(0, 2, f" {title} ", C_TITLE()))

# ── Server list persistence ────────────────────────────────────────────────────

def load_servers():
    if os.path.exists(SERVERS_FILE):
        try:
            with open(SERVERS_FILE) as f:
                data = json.load(f)
            if data:
                return data
        except Exception:
            pass
    save_servers(DEFAULT_SERVERS)
    return list(DEFAULT_SERVERS)

def save_servers(servers):
    try:
        with open(SERVERS_FILE, "w") as f:
            json.dump(servers, f, indent=2)
    except Exception:
        pass

# ── Widgets ────────────────────────────────────────────────────────────────────

def input_dialog(scr, title, prompt, max_len=40, secret=False):
    h, w = scr.getmaxyx()
    dw = min(56, w - 4)
    dh = 5
    win = curses.newwin(dh, dw, (h - dh) // 2, (w - dw) // 2)
    win.keypad(True)
    curses.curs_set(1)
    text = ""

    while True:
        win.erase()
        border(win, title)
        safe(lambda: win.addstr(1, 2, prompt, C_DIM()))
        display = ("*" * len(text)) if secret else text
        safe(lambda: win.addstr(2, 2, f"▶ {display}_", C_HEAD()))
        win.refresh()
        ch = win.get_wch()
        if ch in ('\n', '\r', 10, 13, curses.KEY_ENTER):
            break
        elif ch in ('\x7f', '\b', 127, 263, curses.KEY_BACKSPACE):
            text = text[:-1]
        elif isinstance(ch, str) and ch.isprintable() and len(text) < max_len:
            text += ch

    curses.curs_set(0)
    return text.strip()

def confirm_dialog(scr, prompt):
    h, w = scr.getmaxyx()
    dw = min(len(prompt) + 8, w - 4)
    dh = 5
    win = curses.newwin(dh, dw, (h - dh) // 2, (w - dw) // 2)
    win.keypad(True)
    sel = 1

    while True:
        win.erase()
        border(win, "Confirm")
        safe(lambda: win.addstr(1, 2, prompt[:dw - 4], C_DIM()))
        safe(lambda: win.addstr(3, 4,  " Yes ", C_SEL() if sel == 0 else C_DIM()))
        safe(lambda: win.addstr(3, 12, " No  ", C_SEL() if sel == 1 else C_DIM()))
        win.refresh()
        key = win.get_wch()
        if key in (curses.KEY_LEFT, curses.KEY_RIGHT, '\t'):
            sel = 1 - sel
        elif key in ('\n', '\r', 10, 13, curses.KEY_ENTER):
            return sel == 0
        elif key in ('\x1b', 27):
            return False

def action_menu(scr, inst):
    h, w    = scr.getmaxyx()
    running = inst["state"].lower() == "running"
    name    = inst["name"]
    opts    = (["Connect", "Volumes", "Logs", "Stop", "Remove"] if running
               else ["Start", "Volumes", "Logs", "Remove"])

    dh = len(opts) + 4
    dw = max(30, len(name) + 6)
    win = curses.newwin(dh, dw, (h - dh) // 2, (w - dw) // 2)
    win.keypad(True)
    sel = 0

    while True:
        win.erase()
        border(win, name[:dw - 4])
        for i, label in enumerate(opts):
            attr   = C_SEL() if i == sel else C_DIM()
            prefix = "▶ " if i == sel else "  "
            safe(lambda i=i, label=label, attr=attr, prefix=prefix:
                 win.addstr(2 + i, 3, f"{prefix}{label:<{dw - 7}}", attr))
        safe(lambda: win.addstr(dh - 1, 2, " ESC cancel ", C_DIM()))
        win.refresh()
        key = win.get_wch()
        if key == curses.KEY_UP and sel > 0:
            sel -= 1
        elif key == curses.KEY_DOWN and sel < len(opts) - 1:
            sel += 1
        elif key in ('\n', '\r', 10, 13, curses.KEY_ENTER):
            return opts[sel].lower().split()[0]   # "connect", "logs", "start", "stop", "remove"
        elif key in ('\x1b', 27, 'q', 'Q'):
            return None

def run_with_spinner(scr, msg, fn):
    done   = [False]
    result = [None]
    err    = [None]

    def worker():
        try:
            result[0] = fn()
        except Exception as e:
            err[0] = e
        finally:
            done[0] = True

    threading.Thread(target=worker, daemon=True).start()
    frames = ["|", "/", "-", "\\"]
    i = 0
    h, w = scr.getmaxyx()
    scr.timeout(120)
    while not done[0]:
        status = f" {frames[i % 4]}  {msg} "
        try:
            scr.addstr(h - 1, max(0, w - len(status) - 1), status, C_MSG())
            scr.refresh()
        except curses.error:
            pass
        scr.getch()
        i += 1
    scr.timeout(-1)
    if err[0]:
        raise err[0]
    return result[0]

# ── Log viewer ─────────────────────────────────────────────────────────────────

def show_logs_ssh(scr, ssh, name):
    """Stream docker logs -f in a scrollable pane. [q] to close."""
    lines     = []
    lock      = threading.Lock()
    stop_flag = [False]
    chan_ref   = [None]

    def reader():
        try:
            _, stdout, _ = ssh.exec_command(
                f"docker logs -f --tail 200 {name} 2>&1"
            )
            chan = stdout.channel
            chan_ref[0] = chan
            chan.settimeout(0.5)
            buf = b""
            while not stop_flag[0]:
                try:
                    chunk = chan.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b'\n' in buf:
                        raw, buf = buf.split(b'\n', 1)
                        with lock:
                            lines.append(
                                raw.decode("utf-8", errors="replace").rstrip('\r'))
                except socket.timeout:
                    continue
                except Exception:
                    break
        except Exception:
            pass
        stop_flag[0] = True

    threading.Thread(target=reader, daemon=True).start()

    h, w   = scr.getmaxyx()
    area_h = h - 4
    scroll = 0
    follow = [True]
    scr.timeout(200)

    try:
        while True:
            with lock:
                snap = list(lines)

            if follow[0]:
                scroll = max(0, len(snap) - area_h)

            scr.erase()
            title = f" Logs: {name} "
            safe(lambda: scr.addstr(0, max(0, (w - len(title)) // 2), title, C_TITLE()))
            separator(scr, 1, w)

            for i, line in enumerate(snap[scroll:scroll + area_h]):
                safe(lambda i=i, ln=line[:w - 1]: scr.addstr(2 + i, 0, ln, C_DIM()))

            separator(scr, h - 2, w)
            follow_lbl = "follow:ON " if follow[0] else "follow:OFF"
            ended      = "  (ended)" if stop_flag[0] else ""
            keys = (f" [↑↓/PgUp/PgDn] scroll  [f] {follow_lbl}"
                    f"  [q] close{ended} ")
            safe(lambda: scr.addstr(h - 1, 1, keys[:w - 2], C_DIM()))
            scr.refresh()

            key = scr.getch()
            if key == curses.KEY_UP:
                follow[0] = False
                scroll = max(0, scroll - 1)
            elif key == curses.KEY_DOWN:
                follow[0] = False
                scroll = min(max(0, len(snap) - area_h), scroll + 1)
            elif key == curses.KEY_PPAGE:
                follow[0] = False
                scroll = max(0, scroll - area_h)
            elif key == curses.KEY_NPAGE:
                scroll = min(max(0, len(snap) - area_h), scroll + area_h)
            elif key in (ord('f'), ord('F')):
                follow[0] = not follow[0]
            elif key in (ord('q'), ord('Q'), 27):
                break
    finally:
        stop_flag[0] = True
        scr.timeout(-1)
        try:
            if chan_ref[0]:
                chan_ref[0].close()
        except Exception:
            pass

# ── Readiness watcher ──────────────────────────────────────────────────────────

class ReadyWatcher:
    """Polls Isaac Sim readiness endpoint in the background."""

    def __init__(self):
        self.name      = None
        self.rest_port = 8011
        self.status    = "unknown"   # "unknown" | "loading" | "ready"
        self._stop     = threading.Event()
        self._ssh      = None

    def start(self, ssh_client, name, rest_port):
        self._stop.set()
        self._stop     = threading.Event()
        self.name      = name
        self.rest_port = rest_port
        self.status    = "loading"
        self._ssh      = ssh_client
        threading.Thread(target=self._poll, daemon=True).start()

    def stop(self):
        self._stop.set()
        self.status = "unknown"
        self.name   = None

    def _poll(self):
        while not self._stop.is_set():
            try:
                ok = check_ready(self._ssh, self.rest_port)
                self.status = "ready" if ok else "loading"
            except Exception:
                self.status = "loading"
            if self._stop.wait(5):
                break

# ── Server picker ──────────────────────────────────────────────────────────────

def server_picker(scr):
    """Let user pick or add a server. Returns host string or None."""
    servers = load_servers()
    sel     = 0

    while True:
        h, w = scr.getmaxyx()
        scr.erase()
        title = " Isaac Sim Launcher — Select Server "
        safe(lambda: scr.addstr(0, max(0, (w - len(title)) // 2), title, C_TITLE()))
        separator(scr, 1, w)
        safe(lambda: scr.addstr(2, COL_NAME,      "LABEL", C_HEAD()))
        safe(lambda: scr.addstr(2, COL_NAME + 22, "HOST",  C_HEAD()))
        separator(scr, 3, w)

        for i, srv in enumerate(servers):
            row   = 4 + i
            label = srv.get("label", "")[:20]
            host  = srv.get("host",  "")[:30]
            if i == sel:
                safe(lambda row=row: scr.addstr(row, 0, " " * (w - 1), C_SEL()))
                safe(lambda row=row, l=label:
                     scr.addstr(row, COL_NAME,      f"▶ {l}", C_SEL()))
                safe(lambda row=row, h2=host:
                     scr.addstr(row, COL_NAME + 22, h2,        C_SEL()))
            else:
                safe(lambda row=row, l=label:
                     scr.addstr(row, COL_NAME,      f"  {l}", C_DIM()))
                safe(lambda row=row, h2=host:
                     scr.addstr(row, COL_NAME + 22, h2,        C_DIM()))

        separator(scr, h - 2, w)
        keys = "[↑↓] navigate  [↵] select  [a] add  [d] delete  [q] quit"
        safe(lambda: scr.addstr(h - 1, 1, keys[:w - 2], C_DIM()))
        scr.refresh()

        key = scr.get_wch()
        if key == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif key == curses.KEY_DOWN:
            sel = min(len(servers) - 1, sel + 1) if servers else 0
        elif key in ('\n', '\r', 10, 13, curses.KEY_ENTER):
            if servers:
                return servers[sel]["host"]
        elif key in ('a', 'A'):
            label = input_dialog(scr, "Add Server", "Label (e.g. Lab Server):", max_len=30)
            if label:
                host = input_dialog(scr, "Add Server", "Host IP or hostname:", max_len=60)
                if host:
                    servers.append({"label": label, "host": host})
                    save_servers(servers)
                    sel = len(servers) - 1
        elif key in ('d', 'D'):
            if servers and len(servers) > 1:
                if confirm_dialog(scr, f"Delete '{servers[sel]['label']}'?"):
                    servers.pop(sel)
                    sel = min(sel, len(servers) - 1)
                    save_servers(servers)
        elif key in ('q', 'Q', '\x1b', 27):
            return None

# ── Login screen ───────────────────────────────────────────────────────────────

def login_screen(scr, host):
    """Prompt for SSH credentials for the selected host."""
    h, w = scr.getmaxyx()
    curses.curs_set(1)

    title = " Isaac Sim Launcher — Login "
    safe(lambda: scr.addstr(0, max(0, (w - len(title)) // 2), title, C_TITLE()))
    separator(scr, 1, w)
    host_line = f"SSH host: {host}"
    safe(lambda: scr.addstr(3, max(1, (w - len(host_line)) // 2), host_line, C_DIM()))
    scr.refresh()

    user = input_dialog(scr, "SSH Login", f"Username for {host}:")
    if not user:
        return None
    pw = input_dialog(scr, "SSH Login", "Password:", secret=True)
    if not pw:
        return None
    return user, pw

# ── Volume browser ─────────────────────────────────────────────────────────────

_VCOL_KIND = 2
_VCOL_SRC  = 12
_VCOL_DEST = 48

def show_volumes_ssh(scr, ssh, inst):
    """
    List and manage Docker volumes for a remote container.
    Mounts are split into two labelled sections:
      VITAL  — named Docker volumes (container's own persistent data)
      SHARED — bind mounts from the host (optional extra content)
    """
    name    = inst["name"]
    running = inst["state"].lower() == "running"
    msg     = ""
    sel     = 0   # index into selectable items only

    def load_items():
        out, _, code = run_cmd(
            ssh,
            f"docker inspect --format '{{{{json .Mounts}}}}' {name}",
            timeout=10,
        )
        raw = []
        if code == 0 and out.strip():
            try:
                raw = json.loads(out.strip())
            except json.JSONDecodeError:
                pass

        vital = [m for m in raw if m.get("Type") == "volume"]
        extra = [m for m in raw if m.get("Type") == "bind"]

        items = []
        if vital:
            items.append({"kind": "header", "label": "VITAL VOLUMES",
                          "hcolor": "cyan"})
            for m in vital:
                items.append({"kind": "vital", "mount": m})
        if extra:
            items.append({"kind": "header", "label": "SHARED MOUNTS  (bind)",
                          "hcolor": "yellow"})
            for m in extra:
                items.append({"kind": "extra", "mount": m})
        return items

    def sel_indices(items):
        return [i for i, it in enumerate(items) if it["kind"] != "header"]

    def draw(items):
        scr.erase()
        h, w = scr.getmaxyx()
        title = f" Volumes: {name} "
        safe(lambda: scr.addstr(0, max(0, (w - len(title)) // 2), title, C_TITLE()))
        state_lbl = " ● RUNNING " if running else " ○ STOPPED "
        state_c   = C_RUN()  if running else C_STOP()
        safe(lambda: scr.addstr(0, max(0, w - len(state_lbl) - 1), state_lbl, state_c))
        separator(scr, 1, w)
        safe(lambda: scr.addstr(2, _VCOL_KIND, "KIND",   C_HEAD()))
        safe(lambda: scr.addstr(2, _VCOL_SRC,  "SOURCE", C_HEAD()))
        if w > _VCOL_DEST + 6:
            safe(lambda: scr.addstr(2, _VCOL_DEST, "CONTAINER PATH", C_HEAD()))
        separator(scr, 3, w)

        sidx  = sel_indices(items)
        sel_c = sidx[sel] if sidx and sel < len(sidx) else -1

        if not items:
            safe(lambda: scr.addstr(4, _VCOL_KIND, "No mounts found", C_DIM()))
        else:
            row = 4
            for i, item in enumerate(items):
                if row >= h - 3:
                    break
                if item["kind"] == "header":
                    hc = C_TITLE() if item["hcolor"] == "cyan" else C_MSG()
                    lbl = f" {item['label']} "
                    safe(lambda row=row, lbl=lbl, hc=hc:
                         scr.addstr(row, _VCOL_KIND, lbl, hc | curses.A_BOLD))
                    row += 1
                    continue

                m        = item["mount"]
                is_vital = item["kind"] == "vital"
                src      = (m.get("Name", "") if is_vital
                            else m.get("Source", ""))[:34]
                dest     = m.get("Destination", "")[:28]
                klabel   = "● core  " if is_vital else "○ shared"

                if i == sel_c:
                    safe(lambda row=row: scr.addstr(row, 0, " " * (w - 1), C_SEL()))
                    safe(lambda row=row, k=klabel:
                         scr.addstr(row, _VCOL_KIND, f"▶ {k}", C_SEL()))
                    safe(lambda row=row, s=src:
                         scr.addstr(row, _VCOL_SRC, s, C_SEL()))
                    if w > _VCOL_DEST + 6:
                        safe(lambda row=row, d=dest:
                             scr.addstr(row, _VCOL_DEST, d, C_SEL()))
                else:
                    tc = C_RUN() if is_vital else C_MSG()
                    safe(lambda row=row, k=klabel, tc=tc:
                         scr.addstr(row, _VCOL_KIND, f"  {k}", tc))
                    safe(lambda row=row, s=src, tc=tc:
                         scr.addstr(row, _VCOL_SRC, s, tc))
                    if w > _VCOL_DEST + 6:
                        safe(lambda row=row, d=dest:
                             scr.addstr(row, _VCOL_DEST, d, C_DIM()))
                row += 1

        separator(scr, h - 2, w)
        keys = "[↑↓] navigate  [d] delete core volume  [r] refresh  [q] back"
        safe(lambda: scr.addstr(h - 1, 1, keys[:w - 2], C_DIM()))
        if msg:
            sm = f" {msg} "
            safe(lambda: scr.addstr(h - 1, max(1, w - len(sm) - 1), sm, C_MSG()))
        scr.refresh()

    items = load_items()

    while True:
        sidx = sel_indices(items)
        sel  = max(0, min(sel, len(sidx) - 1)) if sidx else 0
        draw(items)
        msg = ""

        key = scr.get_wch()
        if key == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif key == curses.KEY_DOWN:
            sel = min(len(sidx) - 1, sel + 1) if sidx else 0
        elif key in ('r', 'R'):
            items = load_items()
            msg   = "Refreshed"
        elif key in ('q', 'Q', '\x1b', 27):
            break
        elif key in ('d', 'D') and sidx:
            item = items[sidx[sel]]
            if item["kind"] != "vital":
                msg = "Shared mounts are host paths — remove them from the container config"
                continue
            vol_name = item["mount"].get("Name", "")
            if not vol_name:
                msg = "No volume name found"
                continue
            if running:
                msg = f"Stop the container first before deleting '{vol_name}'"
                continue
            if confirm_dialog(scr, f"Delete volume '{vol_name}'? This is permanent."):
                _, _, code = run_cmd(ssh, f"docker volume rm {vol_name}", timeout=10)
                if code == 0:
                    items = load_items()
                    sidx  = sel_indices(items)
                    sel   = max(0, min(sel, len(sidx) - 1))
                    msg   = f"Deleted {vol_name}"
                else:
                    msg = f"Failed to delete {vol_name} (in use?)"


# ── Main instance list ─────────────────────────────────────────────────────────

def draw_main(scr, instances, sel, connected_name, msg="",
              host="", ready_watcher=None):
    scr.erase()
    h, w = scr.getmaxyx()

    header = " Isaac Sim Launcher — TUI "
    safe(lambda: scr.addstr(0, max(0, (w - len(header)) // 2), header, C_TITLE()))
    if host:
        host_lbl = f" {host} "
        safe(lambda: scr.addstr(0, max(0, w - len(host_lbl) - 1), host_lbl, C_DIM()))
    separator(scr, 1, w)

    safe(lambda: scr.addstr(2, COL_NAME,  "NAME",    C_HEAD()))
    safe(lambda: scr.addstr(2, COL_STAT,  "STATUS",  C_HEAD()))
    safe(lambda: scr.addstr(2, COL_PORTS, "NETWORK", C_HEAD()))
    if w > COL_UP + 6:
        safe(lambda: scr.addstr(2, COL_UP, "UPTIME", C_HEAD()))
    separator(scr, 3, w)

    if not instances:
        safe(lambda: scr.addstr(4, COL_NAME,
             "No Isaac Sim containers found  [n] new  [r] refresh", C_DIM()))
    else:
        for i, inst in enumerate(instances):
            running  = inst["state"].lower() == "running"
            is_conn  = inst["name"] == connected_name
            name_str = (("⚡ " if is_conn else "  ") + inst["name"])[:22]
            base_st  = "● RUNNING" if running else "○ STOPPED"

            # Tunnel badge (independent of readiness)
            tun_sfx = " [tun]" if is_conn else ""

            # Readiness badge — shown for any running watched container
            rdy_sfx = ""
            rdy_c   = None
            if running and ready_watcher and inst["name"] == ready_watcher.name:
                rs = ready_watcher.status
                if rs == "ready":
                    rdy_sfx = " ✓READY"
                    rdy_c   = C_RUN()
                elif rs == "loading":
                    rdy_sfx = " ◌WAIT…"
                    rdy_c   = C_MSG()

            ports  = inst["ports"][:16]
            uptime = inst.get("uptime", "")[:14]
            row    = 4 + i

            if i == sel:
                safe(lambda row=row: scr.addstr(row, 0, " " * (w - 1), C_SEL()))
                safe(lambda row=row, n=name_str:
                     scr.addstr(row, COL_NAME, f"▶ {n}", C_SEL()))
                safe(lambda row=row, s=base_st + tun_sfx + rdy_sfx:
                     scr.addstr(row, COL_STAT, s, C_SEL()))
                safe(lambda row=row, p=ports:
                     scr.addstr(row, COL_PORTS, p, C_SEL()))
                if w > COL_UP + 6:
                    safe(lambda row=row, u=uptime:
                         scr.addstr(row, COL_UP, u, C_SEL()))
            else:
                cs = C_RUN() if running else C_STOP()
                safe(lambda row=row, n=name_str, cs=cs:
                     scr.addstr(row, COL_NAME,  f"  {n}", cs))
                safe(lambda row=row, s=base_st, cs=cs:
                     scr.addstr(row, COL_STAT, s, cs))
                off = COL_STAT + len(base_st)
                if tun_sfx:
                    safe(lambda row=row, sfx=tun_sfx, o=off:
                         scr.addstr(row, o, sfx, C_DIM()))
                    off += len(tun_sfx)
                if rdy_sfx and rdy_c:
                    safe(lambda row=row, sfx=rdy_sfx, c=rdy_c, o=off:
                         scr.addstr(row, o, sfx, c))
                safe(lambda row=row, p=ports:
                     scr.addstr(row, COL_PORTS, p, C_DIM()))
                if w > COL_UP + 6:
                    safe(lambda row=row, u=uptime:
                         scr.addstr(row, COL_UP, u, C_DIM()))

    separator(scr, h - 2, w)
    keys = "[↑↓] navigate  [↵] actions  [n] new  [r] refresh  [l] logs  [q] quit"
    safe(lambda: scr.addstr(h - 1, 1, keys[:w - 2], C_DIM()))
    if msg:
        sm = f" {msg} "
        safe(lambda: scr.addstr(h - 1, max(1, w - len(sm) - 1), sm, C_MSG()))
    scr.refresh()

# ── TUI main loop ──────────────────────────────────────────────────────────────

def tui_main(scr, username, password, host):
    setup_colors()
    curses.curs_set(0)
    scr.keypad(True)

    ssh = None
    try:
        ssh = run_with_spinner(scr, f"Connecting to {host}…",
                               lambda: connect(host, username, password))
    except paramiko.AuthenticationException:
        scr.addstr(4, 2, "SSH authentication failed.", C_STOP())
        scr.addstr(5, 2, "Press any key to exit.", C_DIM())
        scr.refresh()
        scr.getch()
        return
    except Exception as e:
        scr.addstr(4, 2, f"Connection failed: {e}", C_STOP())
        scr.addstr(5, 2, "Press any key to exit.", C_DIM())
        scr.refresh()
        scr.getch()
        return

    instances      = list_instances(ssh)
    sel            = 0
    msg            = f"Connected to {host}"
    connected_name = None
    tunnel_stop    = None
    ssh_tun        = None
    ready_watcher  = ReadyWatcher()

    def update_watcher():
        """Point the readiness watcher at the first running container, if any."""
        running = [i for i in instances if i["state"].lower() == "running"]
        if running:
            r = running[0]
            if ready_watcher.name != r["name"]:
                ready_watcher.start(ssh, r["name"], r.get("rest_port", 8011))
        else:
            ready_watcher.stop()

    def refresh():
        nonlocal instances
        instances = list_instances(ssh)
        update_watcher()

    update_watcher()   # start polling immediately on first load

    # 2-second timeout so readiness badge updates without a keypress
    scr.timeout(2000)

    while True:
        sel = max(0, min(sel, len(instances) - 1)) if instances else 0
        draw_main(scr, instances, sel, connected_name, msg,
                  host=host, ready_watcher=ready_watcher)
        msg = ""

        try:
            key = scr.get_wch()
        except curses.error:
            continue    # timeout → loop back, redraw with fresh readiness status

        if key == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif key == curses.KEY_DOWN:
            sel = min(len(instances) - 1, sel + 1) if instances else 0

        elif key in ('r', 'R'):
            refresh()
            msg = "Refreshed"

        elif key in ('q', 'Q', '\x1b', 27):
            break

        elif key in ('l', 'L') and instances:
            scr.timeout(-1)
            show_logs_ssh(scr, ssh, instances[sel]["name"])
            scr.timeout(2000)

        elif key in ('n', 'N'):
            scr.timeout(-1)
            tag = input_dialog(scr, "New Instance",
                               "Short name (e.g. alice, research-1):")
            scr.timeout(2000)
            if tag:
                safe_name = re.sub(r'[^a-zA-Z0-9_-]', '-', tag).strip('-')
                if not safe_name:
                    msg = "Invalid name"
                else:
                    running_count = sum(
                        1 for inst in instances
                        if inst["state"].lower() == "running")
                    if running_count > 0:
                        scr.timeout(-1)
                        ok_go = confirm_dialog(
                            scr,
                            "Another instance is running (host-net). Start anyway?")
                        scr.timeout(2000)
                        if not ok_go:
                            continue
                    scr.timeout(-1)
                    ok, err = run_with_spinner(
                        scr, f"Starting isaac-sim-{safe_name}…",
                        lambda sn=safe_name: start_managed_instance(ssh, sn))
                    scr.timeout(2000)
                    refresh()
                    msg = (f"Started isaac-sim-{safe_name}" if ok
                           else f"Failed: {err[:40]}")

        elif key in ('\n', '\r', 10, 13, curses.KEY_ENTER) and instances:
            inst   = instances[sel]
            scr.timeout(-1)
            action = action_menu(scr, inst)
            scr.timeout(2000)

            if action == "connect":
                if inst["state"].lower() != "running":
                    msg = "Instance is not running — start it first"
                    continue
                if tunnel_stop:
                    tunnel_stop.set()
                ready_watcher.stop()
                tunnel_stop    = threading.Event()
                connected_name = inst["name"]
                rest_port      = inst["rest_port"]
                webrtc_port    = inst["webrtc_port"]
                try:
                    if ssh_tun:
                        try:
                            ssh_tun.close()
                        except Exception:
                            pass
                    ssh_tun   = connect(host, username, password)
                    transport = ssh_tun.get_transport()
                    for lp, rp in ((rest_port, rest_port),
                                   (webrtc_port, webrtc_port)):
                        threading.Thread(
                            target=run_tunnel_server,
                            args=(lp, rp, transport, tunnel_stop),
                            daemon=True,
                        ).start()
                    ready_watcher.start(ssh, connected_name, rest_port)
                    msg = (f"Tunnels active → localhost:{rest_port}, "
                           f"localhost:{webrtc_port}")
                except Exception as e:
                    msg = f"Tunnel error: {e}"
                    connected_name = None

            elif action == "volumes":
                scr.timeout(-1)
                show_volumes_ssh(scr, ssh, inst)
                scr.timeout(2000)

            elif action == "logs":
                scr.timeout(-1)
                show_logs_ssh(scr, ssh, inst["name"])
                scr.timeout(2000)

            elif action == "stop":
                n = inst["name"]
                scr.timeout(-1)
                run_with_spinner(scr, f"Stopping {n}…",
                                 lambda name=n: stop_container(ssh, name))
                scr.timeout(2000)
                if connected_name == n:
                    if tunnel_stop:
                        tunnel_stop.set()
                    ready_watcher.stop()
                    connected_name = None
                refresh()
                msg = f"Stopped {n}"

            elif action == "start":
                n = inst["name"]
                scr.timeout(-1)
                run_with_spinner(scr, f"Starting {n}…",
                                 lambda name=n: start_container(ssh, name))
                scr.timeout(2000)
                refresh()
                msg = f"Started {n}"

            elif action == "remove":
                n = inst["name"]
                scr.timeout(-1)
                ok_go = confirm_dialog(scr, f"Remove {n}?")
                scr.timeout(2000)
                if ok_go:
                    scr.timeout(-1)
                    run_with_spinner(scr, f"Removing {n}…",
                                     lambda name=n: remove_container(ssh, name))
                    scr.timeout(2000)
                    if connected_name == n:
                        if tunnel_stop:
                            tunnel_stop.set()
                        ready_watcher.stop()
                        connected_name = None
                    refresh()
                    msg = f"Removed {n}"

    # Cleanup
    ready_watcher.stop()
    if tunnel_stop:
        tunnel_stop.set()
    if ssh_tun:
        try:
            ssh_tun.close()
        except Exception:
            pass
    if ssh:
        try:
            ssh.close()
        except Exception:
            pass


def run_tui(username=None, password=None):
    """Entry point: server picker → login → main loop."""

    def _main(scr):
        setup_colors()
        curses.curs_set(0)
        scr.keypad(True)

        host = server_picker(scr)
        if not host:
            return

        nonlocal username, password
        if not username or not password:
            creds = login_screen(scr, host)
            if not creds:
                return
            username, password = creds

        tui_main(scr, username, password, host)

    curses.wrapper(_main)


if __name__ == "__main__":
    run_tui()
