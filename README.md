# RTE Hosting — Minecraft Java Server Manager

**Development release v0.2.0** — a functional Python/Windows server launcher and modern browser-based control panel themed with RTE Hosting's provided graphics. This is an initial implementation, **not a production multitenant hosting platform**.

## Included now

- Dark graphite / electric-blue desktop interface with supplied RTE Hosting branding, embedded Windows Edge WebView (fallback: default browser).
- Local web portal on **http://127.0.0.1:8080**, adjustable with `RTE_PORT`.
- One-time local administrator enrollment, PBKDF2-SHA256 password hashes, login lockout, HttpOnly SameSite session cookies, CSRF checks, role-aware data access, access/audit logs.
- Staff can create servers and customer accounts and explicitly assign start/stop, console, and file permissions per server.
- Supports manual import of installed server distributions: **Vanilla, Bukkit, Spigot, Paper, Purpur, Fabric, Forge, NeoForge, Quilt, Mohist, Arclight, Other**.
- Java jar-based launcher with individual memory allocation, port tracking, live text console, console commands and graceful stop command.
- Windows `run.bat` launch mode for Forge / NeoForge and other frameworks requiring generated bootstrap scripts (requires installed server files).
- Server-specific file manager: list, create folder, upload/download/delete files, edit UTF-8 text, configure selected `server.properties` settings.
- Explicit acceptance flow for the Minecraft EULA.
- Offline `.zip` backups with no automatic restore in this release.
- Branded **Inno Setup Windows installer specification** and automated **GitHub Actions Windows build** producing `RTEHosting-Setup-v0.1.0.exe` plus a portable folder.

## Local quick start (developer)

Install Python **3.12+**, a compatible Java runtime, and optionally `pywebview` for desktop embedding. The backend itself uses only the Python standard library.

```powershell
py -3.12 run.py
```

Open `http://127.0.0.1:8080` on the hosting computer. On the first visit, create a strong administrator account. The site starts with **no pre-created accounts or Minecraft servers**.

For a headless local portal (keep the process alive to manage running servers):

```powershell
py -3.12 run.py --headless --port 8080
```

Server files, databases and backups are stored at `%LOCALAPPDATA%\RTE Hosting` by default. Override with `RTE_HOSTING_DATA` to choose a dedicated location. **Keep the database and server folders on a trusted disk with restrictive Windows filesystem permissions.**

## Create a Minecraft server

1. Install a Java runtime compatible with the selected Minecraft release and framework. In the server creation form, leave `java` to use the runtime in `PATH`, or enter the approved absolute `java.exe` path.
2. Choose **New server**, framework label and version, game port, heap memory sizes, and launcher type. Each instance creates its own isolated *folder path* and stores its port metadata.
3. Use **Files** to upload your compatible Minecraft server `.jar`. For Paper/Spigot/Vanilla/Fabric and applicable hybrid distributions, choose the `.jar` startup mode. For Forge/NeoForge use the framework's **official installer** to prepare the full server directory and the generated Windows `run.bat`, then choose script mode.
4. Read and explicitly accept the [Minecraft EULA](https://aka.ms/MinecraftEULA).
5. Start the process and inspect the Console. To connect from Minecraft, use the Windows host's reachable IP address and the selected port. Game ports must be allowed by your Windows firewall/router separately.

**Notes:** The app does not automatically download Minecraft server distributions or install Forge dependencies. The `framework` label does not guarantee framework compatibility; bring a correctly installed runtime/distribution. Forge/NeoForge `run.bat` may require `JAVA_HOME` set for its own script. The browser uploader caps each file at 64 MiB; large modpacks/worlds should be copied by host staff into the instance's data folder directly.

## Compile a real Windows executable and installer

> The source bundle includes a complete Windows build/installer *recipe*. The `.exe` binaries can only be compiled/tested on a Windows build runner; this Linux environment cannot certify a compiled Windows installer.

### Windows build

1. Install Python 3.12 for Windows and [Inno Setup 6](https://jrsoftware.org/isinfo.php).
2. Open PowerShell in the project root and run:

```powershell
.\build\build-windows.ps1
```

The build uses PyInstaller to package `run.py` and its bundled assets into `dist\RTEHosting\RTEHosting.exe`, then Inno Setup compiles `release\RTEHosting-Setup-v0.1.0.exe`. The installer adds Start Menu shortcuts, optionally a desktop shortcut, and offers to launch the app after installation. `build/rte-hosting.ico`, `wizard-large.bmp`, and `wizard-small.bmp` provide branded icons/artwork.

### Automated build (GitHub Actions)

See **GITHUB_BUILD_GUIDE.md** for step-by-step instructions to create the dedicated repository, trigger the workflow, and retrieve the Windows installer. The CI job also runs Python regression tests and checks that the compiled Windows `.exe` serves its bootstrap API before uploading the installer.

Push the project files to your chosen GitHub repository and run **Actions → Build RTE Hosting Windows Installer → Run workflow**. Its Windows runner compiles both release artifacts, which can be downloaded from that workflow's Artifacts area. The workflow intentionally does **not** publish a public release or auto-deploy servers.

## Accounts and assignments

- **Admin:** full control; can create all account types, servers, and permissions.
- **Staff:** full control of server instances; can provision customers, but cannot create other staff/admin users.
- **Customer:** sees only explicitly assigned instances, with separate flags for `can_control`, `can_console`, `can_files`. Console commands have Minecraft server operator powers, so leave disabled unless required.

Use **Team & Access** → Create account / Assign server to provision individual customer accounts. Users connect over HTTPS to your portal hostname (see below), not via RDP.

## Web, SFTP and remote administration

By default the portal is **bound to localhost**. For production remote portal hosting, use a TLS-terminating reverse proxy (e.g. IIS/ARR or Caddy) that forwards HTTPS to `127.0.0.1:8080`. Set environment variable `RTE_ALLOWED_HOSTS` to the external portal host in addition to localhost, e.g. `localhost,127.0.0.1,hosting.example.com`; set `RTE_SECURE_COOKIE=1`. Restrict proxy forwarding, apply host firewall limits and keep HTTPS on at all times. Directly exposing port 8080 to the public internet is **not recommended**.

RDP and SFTP are **integration/design points, not activated services** in this release. For RDP, limit access to designated Windows host administrators over a VPN/RD Gateway. For SFTP, use Windows OpenSSH with isolated OS accounts and restrictive NTFS ACLs; assign users' actual OS permissions as appropriate. **Never expose plain FTP credentials** and never treat an RTE web user as a Windows security principal. The web file manager is already functional without FTP.

## Known release limitations

- Windows Service/always-on execution, Windows OS-level per-instance sandboxing, automated framework downloads, Java version auto-detection, scheduled backups, backup restoration, customer self-service password resets, multi-factor authentication, storage quotas and true SFTP account provisioning are **not implemented**.
- Active process tracking exists only while this manager process remains running. Run the controller persistently while servers are active. Closing the desktop/control service sends Minecraft `stop` to managed processes and waits for them to shut down, so keep the manager running while hosting.
- Minecraft mods, plugins and server startup scripts run executable code with the launcher Windows account's permissions. **Untrusted tenant isolation is not provided**.
- Automated server/backup lifecycle cleanup and database migrations require additional work for production.

Read **SECURITY.md** before any LAN/internet deployment.

## Run API integration tests

```powershell
py -3.12 -m unittest discover -s tests -v
```

## Brand assets

`rte_hosting/static/logo.png` and `rte_hosting/static/brand-bg.jpg` are derived from the graphics provided for this project. The original colors informed the cobalt/electric-blue, white and charcoal palette.

## v0.2.0 update

See [RELEASE_NOTES_v0.2.md](RELEASE_NOTES_v0.2.md) for import-in-place, automatic Java detection, official framework downloads, optional built-in SFTP, RDP connection profiles, security cautions and upgrade instructions. An in-place import **does not copy worlds**, but it does allow operations to modify the original directory. Forge/NeoForge and other complex installers remain manual.
