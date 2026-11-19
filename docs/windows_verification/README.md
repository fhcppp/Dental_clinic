# Native Windows x64 verification — NOT RUN

Execute on a disposable, dedicated Windows x64 test workstation, not on the production clinic database:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install pywin32 sqlcipher3
.\.venv\Scripts\python docs\windows_verification\verify_windows.py
```

Check Python/Windows architecture and native dependency licenses before installing. If native bindings are unavailable or installation fails, report UNVERIFIED/blocked; never switch to unencrypted production SQLite. No credentials or keys should be pasted into GitHub or ChatGPT.

Additional manual acceptance steps: verify Windows wheel/DLL distribution licensing and signatures; test DPAPI across user accounts and workstation reboot; test password recovery on an independent Windows workstation; test encrypted backup restore with attachments; verify offline operation and anti-malware compatibility; build a separate Windows test installer only after the backend completion gate passes. Record operating system build, Python architecture, dependency versions and exact output. Linux mocks or this smoke test alone are not a production release gate.
