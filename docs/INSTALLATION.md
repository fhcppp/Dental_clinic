# Development installation (not clinic deployment)

Requires Python 3.11+ and a writable local filesystem. From a verified source
checkout, create a virtual environment and run:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m unittest discover -s tests -v
```

This installs **only a Python library**; it does not create a Windows desktop
application or a clinic database automatically. See `README.md` for a
synthetic-data usage example. Dependency installation may require internet
unless you provision a trusted offline wheelhouse. Don't put project data in
a cloud-synchronized folder. For real deployments, encryption, access control,
installer signing and backup are mandatory prerequisites.
