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

## File Overview

```
Launch IsaacSim.bat     ← Double-click this to launch the GUI
isaac_sim_launcher.py   ← The launcher GUI (Python source)
isaac_sim_creds.json    ← Auto-generated saved credentials (password is encrypted)
.isaac_sim.key          ← Auto-generated Fernet encryption key (hidden file)
README.md               ← This file
```

> **Security note:** Saved passwords are encrypted at rest using [Fernet symmetric encryption](https://cryptography.io/en/latest/fernet/) (AES-128-CBC + HMAC). The encryption key is stored in `.isaac_sim.key` (a hidden file). While this is much safer than plain text, anyone with access to **both** files on the same machine can decrypt the password. Do **not** commit either file to version control. Add both to your `.gitignore`:
> ```
> isaac_sim_creds.json
> .isaac_sim.key
> ```
