# Isaac Sim Launcher

A GUI tool that automates launching NVIDIA Isaac Sim on the remote GPU server via SSH, including Docker container management, port forwarding, and readiness monitoring.

---

## Pre-Setup Checklist

Before running the launcher, make sure the following are in place on your machine:

### 1. Install Python 3.8+
- **Windows (Scoop):** `scoop install python`
- **Windows (Official):** Download from [python.org](https://www.python.org/downloads/)
- **Verify:** Open a terminal and run:
  ```
  python --version
  ```

### 2. Install the `paramiko` library
This is the only external dependency. Run:
```
pip install paramiko
```
If you have multiple Python installations (e.g., Anaconda + system Python), make sure you install it for the Python you'll use to run the script:
```
python -m pip install paramiko
```

### 3. Have your SSH credentials ready
You need a valid username and password for the remote host (`10.158.244.8`). The launcher will prompt you on first run and can save them locally for convenience.

### 4. Network access
Make sure you can reach `10.158.244.8` from your network. If you are off-campus or off-VPN, connect to the appropriate VPN first.

### 5. No conflicting local ports
The launcher will forward **ports 8011 and 49100** from the remote machine to your `localhost`. Make sure nothing else is already using those ports. You can check with:
```
# Windows
netstat -ano | findstr :8011

# macOS / Linux
lsof -i :8011
```

---

## How to Run

### Easiest: Double-click the batch file
Just double-click **`Launch IsaacSim.bat`** — that's it. It handles everything automatically. If Python or paramiko is missing, it will print a helpful error message instead of silently closing.

> **Tip:** Right-click the `.bat` file → **Send to** → **Desktop (create shortcut)** for quick access.

### Alternative: Run from terminal
```
python isaac_sim_launcher.py
```

1. A **login dialog** will appear — enter your SSH username and password.  
   Check **"Remember credentials"** to save them locally (stored in `isaac_sim_creds.json` next to the script).

2. Click **"▶ Run Isaac Sim"**. The launcher will:
   - SSH into the remote server
   - Stop and remove any existing `isaac-sim` Docker container
   - Start a new container with the correct volume mounts and settings
   - Run `./runheadless.sh -v` inside the container
   - Open SSH tunnels so you can access Isaac Sim locally
   - Poll the readiness endpoint every 5 seconds

3. The **status indicator** (top-right) will turn **green** and say **"✓ READY"** once Isaac Sim is fully loaded and accepting connections.

4. When you're done, click **"■ Stop"** to gracefully shut down the container and close all SSH connections.

---

## What Each Button Does

| Button | Action |
|--------|--------|
| **▶ Run Isaac Sim** | Starts the full pipeline (SSH → Docker → Headless → Tunnels → Monitor) |
| **■ Stop** | Sends `docker stop isaac-sim`, closes SSH tunnels, and resets the UI |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'paramiko'` | Run `pip install paramiko` (or `python -m pip install paramiko`) |
| "Auth failed" error | Double-check your SSH username and password. Delete `isaac_sim_creds.json` to re-enter. |
| Stuck on "Waiting for readiness" | Isaac Sim can take 5-10 minutes to fully initialize. Check the output log for errors. |
| "Port already in use" | Close any other applications using ports 8011 or 49100, or kill old SSH tunnels. |
| Can't reach the host | Make sure you're on the correct network/VPN. Try `ping 10.158.244.8`. |

---

## Managed Instances panel (new — backwards compatible)

The GUI now has a **Managed Instances** section below the Run/Stop buttons. This panel talks to the **Isaac-Sim-Manager** running on the server and lets you see and control named instances created by that tool.

**The original Run / Stop buttons are unchanged.** If you just want to start a fresh `isaac-sim` container the old way, ignore this panel entirely.

| Button | Action |
|--------|--------|
| **↺ Refresh** | SSH to the server and list all Isaac Sim containers |
| **⚡ Connect** | Set up SSH tunnels to the selected running instance |
| **▶ Start** | Start the selected stopped container |
| **■ Stop** | Stop the selected running container |

---

## TUI mode

If you prefer a terminal interface (or are running headless), add `--tui`:

```bash
python isaac_sim_launcher.py --tui
```

Keyboard controls are the same as Isaac-Sim-Manager: `↑↓` navigate, `Enter` for actions, `n` to create a new managed instance, `r` to refresh, `q` to quit. Selecting **Connect** sets up SSH tunnels and shows the ports.

---

## Linux Alias Setup

To launch the TUI with a short `isaac` command, add an alias to your `~/.bashrc`:

```bash
echo "alias isaac='python3 /home/$(whoami)/Engineering/Projects/Isaac_Sim_Launcher/isaac_sim_launcher.py --tui'" >> ~/.bashrc
source ~/.bashrc
```

After that you can start the TUI from any terminal with:

```bash
isaac
```

> **Note:** The alias uses an absolute path. If you move the repo, update the path in `~/.bashrc` to match.  
> **Dependencies:** Make sure `paramiko` and `cryptography` are installed for the Python interpreter on your `PATH`:
> ```bash
> pip install paramiko cryptography
> ```

---

## File Overview

```
Launch IsaacSim.bat     ← Double-click this to launch the GUI
isaac_sim_launcher.py   ← Launcher GUI + --tui entry point (Python source)
backend.py              ← Shared SSH/Docker logic (used by GUI panel + TUI)
tui.py                  ← Curses TUI (used by --tui mode)
isaac_sim_creds.json    ← Auto-generated saved credentials (password is encrypted)
.isaac_sim.key          ← Auto-generated Fernet encryption key (hidden file)
README.md               ← This file
```

> **Security note:** Saved passwords are encrypted at rest using [Fernet symmetric encryption](https://cryptography.io/en/latest/fernet/) (AES-128-CBC + HMAC). The encryption key is stored in `.isaac_sim.key` (a hidden file). While this is much safer than plain text, anyone with access to **both** files on the same machine can decrypt the password. Do **not** commit either file to version control. Add both to your `.gitignore`:
> ```
> isaac_sim_creds.json
> .isaac_sim.key
> ```
