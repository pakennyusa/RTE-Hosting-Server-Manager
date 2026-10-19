# RTE Hosting — produce the Windows `.exe` installer on GitHub

## First-time setup

1. Create a **new, private** GitHub repository named `RTE-Hosting-Server-Manager` under an account with access to GitHub Actions. Do **not** upload this project into your existing `RTE-Cinema` or Pegasus repositories.
2. Extract the **contents** of this ZIP directly into the repository root, preserving `.github/workflows/windows-installer.yml` and the other folders. The workflow file must not end up under an extra folder like `rte_hosting_release_ready/`.
3. Commit and push to the default `main` branch. With Git installed, an empty repo is initialized as follows (substitute your own repository URL):

   ```powershell
   git init -b main
   git add .
   git commit -m "Initial RTE Hosting server manager and branded Windows installer"
   git remote add origin https://github.com/YOUR_ACCOUNT/RTE-Hosting-Server-Manager.git
   git push -u origin main
   ```

4. In the repository, open **Actions → Build RTE Hosting Windows Installer**. The initial push should automatically trigger a run; otherwise select **Run workflow** on `main`.
5. When the workflow shows a **green check**, open the run's **Artifacts** section. Download **RTEHosting-Windows-Installer** for `RTEHosting-Setup-v0.1.0.exe`. **RTEHosting-Portable** contains the unpacked standalone desktop application.
6. Install on Windows 10/11 x64. Windows may show a SmartScreen prompt for unsigned executables. Inspect the source and sign the release before distributing it commercially.

## What the CI pipeline verifies

- Python account/permission/backend regression tests.
- PyInstaller packaging and Inno Setup compiler success on a Windows runner.
- A real Windows smoke test that runs the packaged `.exe` as a headless process on a temporary localhost port and verifies its bootstrap API.
- Both artifacts exist before publishing them for download.

## Current limitations

The desktop `.exe` is an initial local-first hosting manager, **not** a Windows Service. Do not expose customer access publicly or sell untrusted hosting until process isolation, TLS hardening, backups/restores, and operations controls are implemented. See `SECURITY.md`.

This build project does not itself provide a signed installer or host a web portal. GitHub Actions artifact retention is 30 days. No license has been granted for third-party Minecraft distribution binaries; supply your own compliant server runtimes.
