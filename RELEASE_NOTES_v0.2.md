# RTE Hosting Server Manager — v0.2.0

## What's new

- **Import existing Minecraft folders in place**: supply an absolute local path on the hosting machine; inspect world files, available `.jar`s, `run.bat`, `server.properties` port, and `eula.txt`, then confirm before linking. No world duplication; all subsequent start/stop, file management and backups act on the original directory.
- **Multiple managed instances**: SQLite `workspace` column with additive migration for existing v0.1 installations. A default managed instance still uses RTE's own servers directory. The original data, users, assignments, and backups are preserved on upgrade.
- **Version-aware framework installation**: browse official releases for Vanilla, Paper, Purpur, Fabric; install/update from official vendor endpoints. TLS host allowlist, Paper SHA-256 and Mojang SHA-1 verification, bounded downloads, and atomic same-JAR replacement; no duplicated worlds or extra JAR for in-place imports. Purpur and Fabric downloads come from official providers without published hashes through the selected API endpoints.
- **Java detection and selection**: inventory installed Java executables, recommend a version based on Minecraft version, choose automatically at start or pin an installed runtime manually. Forge/NeoForge `run.bat` can receive selected `JAVA_HOME` and `PATH`. RTE **does not install the JDK itself** in this release.
- **Secure SFTP server (optional)**: built-in Paramiko SSH/SFTP service with persistent host key, password login, per-user assigned-server directory tree, and protection against traversal and edits to privileged server boot files. Disabled by default; start with `--sftp-port 2222` or set `RTE_SFTP_PORT=2222`. Localhost-only by default. Use SSH tunnel/VPN or explicitly opt into LAN binding with firewall rules; never expose plaintext FTP.
- **Administrator RDP helper**: set `RTE_RDP_HOST` on the Windows host to enable download of a credential-free `.rdp` configuration from Settings. Uses Windows RDP and its own Windows credentials; **does not enable RDP, create Windows accounts, or grant customers desktop access**.
- Branded setup installer, Java runtime and vendor installer UI, updated Windows CI smoke tests, expanded regression tests.

## Known limitations and important cautions

This is a **development build**. The portal is bound to `127.0.0.1:8080` by default. Never expose it over unauthenticated HTTP to the internet. Configure a vetted TLS proxy with access control and/or VPN, and use Windows NTFS isolation before hosting mutually untrusted customers. Imported folders must be stopped in any old launcher first. Windows RDP has system-level privileges; customers must not be granted host desktop access. Manual framework bootstrap remains necessary for Forge, NeoForge, Mohist, Spigot and other multi-step or unverified vendor installers.

Before framework changes, take an offline backup and review game version/mod/plugin compatibility. Automatic framework updates are explicit only (never silent).

## Upgrade

Install the v0.2.0 setup over the v0.1.0 installation. The installer shares the same `AppId` and app directory; user data resides under the per-user `RTE Hosting` data directory and is not removed by the installer. Initial startup adds the `workspace` column if missing. Back up your local RTE database and any production Minecraft worlds before upgrading.

## Quick walkthrough

1. Start RTE Hosting, sign in with an administrator or staff account.
2. Select **Import existing**. Paste the full existing Minecraft folder path on the Windows host. Select **Inspect this folder**, review detected settings, and confirm in-place writes.
3. In the server overview, choose **Select Java** or keep automatic JDK selection; choose **Install / update framework** to download an available official release, if desired. Existing startup JAR files are replaced atomically rather than stored twice.
4. Optionally run the app with `--sftp-port 2222`. In WinSCP or FileZilla: protocol SFTP, host `127.0.0.1` (or tunneled hostname), port 2222, RTE portal username/password. Server directories appear by **server ID**. Customer access is limited to assigned instances with Files enabled.
5. Admin RDP profile: set `RTE_RDP_HOST=your-internal-windows-host.example` and restart the app; under Settings, download the `.rdp` file. Enable Windows Remote Desktop separately and secure it behind a VPN/RD Gateway with MFA.
