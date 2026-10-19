# RTE Hosting security model — starter release

This project is a **local-first prototype** and should not be treated as production-ready multi-tenant Minecraft infrastructure.

## Implemented protections

- Passwords stored as 600,000-round PBKDF2-SHA256 salted digests; usernames unique case-insensitively.
- Server-side sessions, fixed 12-hour expiry, `HttpOnly`, `SameSite=Strict`; optional `Secure` cookie flag when deployed behind HTTPS.
- Requests that modify server state require a unique anti-CSRF token; cross-origin requests are rejected and allowed hostnames can be configured to prevent DNS rebinding.
- Web data is assigned-server scoped. Staff-only endpoints enforce role permissions in the backend, not merely in the interface.
- File browsing verifies canonical paths stay within the designated instance directory; uploads have a 64-MiB/request limit.
- Customers cannot upload Windows command/script executables or overwrite main boot files via the portal, although mods and plugins they are allowed to upload can execute arbitrary Java code.
- The HTTP listener binds `127.0.0.1` unless an operator explicitly allows otherwise.
- Audit events are logged for logins and administrative changes; command content is redacted.

## Mandatory deployment requirements before selling public hosting

1. **Isolate Minecraft processes:** each server must run under a distinct restricted Windows account or dedicated VM/container. Folder-scoped web file access **does not** prevent a malicious plugin or mod from reading host files when Java runs as the same account as the launcher.
2. **TLS everywhere:** use a hardened HTTPS reverse proxy or VPN for customer access; enable secure session cookies. Do not expose cleartext port 8080 to the public internet.
3. **RDP:** use RD Gateway/VPN and staff-only Windows accounts; never attach customer accounts to host-level RDP.
4. **SFTP:** provision separate Windows/OpenSSH identities and NTFS ACLs, preferably one service principal per tenant. Plain FTP is unsafe unless protected with explicit TLS and appropriate controls.
5. **Backups:** implement storage quota, retention policy, restore validation, scheduled backup, and offline/offsite recovery.
6. **Credentials:** implement account lockouts across distributed origins, password reset with secure enrollment, optional MFA, per-account session revocation and disaster recovery.
7. **Host hardening:** minimize privileges, configure Windows firewall for game ports only, maintain Java runtimes, monitor resources, sign releases, ship trusted update manifests and keep an incident log.
8. **Availability:** run the controller as a dedicated Windows Service, design persistent process ownership/recovery and test crash-recovery behavior.

## Scope of this release

The included installer adds a per-user desktop application, not a background Windows Service. RDP and SFTP are not created by installing the package. Do not confuse role restrictions in the web portal with a Windows sandbox.

## v0.2 additions

SFTP is disabled by default. It is encrypted and limited to assigned server file trees, but it does not isolate arbitrary executable mod/plugin code: **Minecraft processes and RTE Hosting still run under the same OS identity.** Require a VPN/SSH tunnel for remote file access, avoid weak passwords, and block untrusted ports at the Windows firewall. The SFTP host key is persisted under the per-user RTE data folder; protect that folder's Windows NTFS ACLs and back up the private key securely. RDP profiles have no passwords; they do not provision local Windows accounts or remote access rights. Never give non-staff users RDP host access.

Imported server directories are actively managed in place. Always stop any preexisting Minecraft process first, confirm the import target, and ensure file permissions restrict other tenants. Framework downloads are restricted to official HTTPS endpoints and require a stopped server. Back up worlds before making framework changes.
