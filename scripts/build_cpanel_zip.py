"""Build the upload package for cPanel (or any server): dist/wikischolar-cpanel.zip.

    python scripts/build_cpanel_zip.py

Includes the code, templates, static files, seed data and docs. Leaves out everything that is
local-only or secret: virtualenv, portable PostgreSQL and its data, caches, collected static
files, the local .env and the Windows dev launcher. Upload the zip into the cPanel application
root and extract it; it never contains a .env, so the server's settings are not overwritten.
"""
import os
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "dist" / "wikischolar-cpanel.zip"
SKIP_DIRS = {".venv", ".pgsql", ".pgdata", "__pycache__", "dist", ".claude", "staticfiles", ".git", "scripts"}
SKIP_FILES = {".env", ".env.bak", "run-dev.ps1"}


def main():
    OUT.parent.mkdir(exist_ok=True)
    count = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirs, files in os.walk(ROOT):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(files):
                if name in SKIP_FILES or name.endswith((".pyc", ".zip")):
                    continue
                path = pathlib.Path(dirpath) / name
                z.write(path, path.relative_to(ROOT).as_posix())
                count += 1
    print(f"{count} files, {OUT.stat().st_size // 1024} KB -> {OUT}")


if __name__ == "__main__":
    main()
