# RTE Hosting architecture

## v0.1 functional architecture

```text
Branded Windows desktop launcher (PyInstaller .exe + Edge WebView)
                           |
                           | loopback HTTP / REST on port 8080
                           v
           RTE Hosting portal (Python HTTP server)
             |             |               |
      Session security  SQLite DB      Role-based API
             |             |               |
             +-------------+---------------+
                           |
                  Minecraft Manager
             /             |              \
        Server A        Server B        Server C
        Java JAR        Java JAR         run.bat
             |             |              |
       own files / ports / logs / backups (no OS isolation)
```

The shared frontend is a responsive web management UI. The packaged executable opens it as a native desktop window. Customers use the same frontend through an HTTPS reverse proxy with customer-scoped permissions. Role/access checks are always performed server-side.

## Security boundaries

RTE's user account and server-assignment database is **not** the Windows identity database. A customer can see only an assigned server's files through the web API, but Java plugins and mods run natively under the manager process identity in this first release. The manager is therefore intended only for trusted local deployments.

## Proposed production evolution

### Windows service and server ownership

Split into two executables: **RTE Host Agent** (Windows Service, starts on boot, auto-recovers running servers) and **RTE Hosting Control Center** (desktop UI and web API client). Communicate over an authenticated local named pipe with per-request policy validation. Maintain instance state even if no user is logged into the desktop. Track child processes via Windows Job Objects and use safe recovery/restart semantics.

### OS-isolated customers

Run each Minecraft instance as an individual restricted Windows service account or in a dedicated VM. Separate ACLs, CPU/memory/storage quotas, TCP ports, and Java runtime selection. Server mods/plugins are untrusted executable code even when uploaded as a `.jar`. Never run tenant-uploaded `run.bat` under a privileged host admin identity.

### Framework catalog and installers

A real catalog will fetch from trusted official metadata endpoints, show version/build selections, verify hashes/signatures where available, and install required dependencies for Vanilla, Paper, Purpur, Fabric, Forge, NeoForge, etc. Avoid inventing URLs or hard-coding unstable third-party build endpoints. Hybrid frameworks require additional compatibility checks.

### RDP, SFTP and portal

Use RDP only for trusted hosting staff through Windows Remote Desktop Gateway/VPN. Manage customer file transfer through **SFTP** with a per-user Windows/OpenSSH identity confined by NTFS ACLs or another vetted SFTP subsystem. Plain FTP must never be enabled by default. For web access use TLS, automated certificate rotation, strong session management, optional MFA, recoverable password flows and delegated staff permissions.

### Operations

Add true scheduled backup/restore, retention policy, compression with resource limits, modpack upload pipeline, remote consoles over a controlled websocket, monitoring, metrics, configurable auto-restart, console search, a Java runtime manager, IP/port allocation, SMTP notifications, multi-host agent federation and safe automatic updates.
