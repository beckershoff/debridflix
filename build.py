#!/usr/bin/env python3
"""Builds dist/enigma2-plugin-extensions-debridflix_<version>_all.ipk (stdlib only). Run from the repo root."""
import io, os, re, tarfile, time

ROOT = "DebridFlix"
DEST = "usr/lib/enigma2/python/Plugins/Extensions/DebridFlix"
VERSION = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "core", "__init__.py")).read()).group(1)


def clean(info):
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    return None if "__pycache__" in info.name else info


def tgz(add):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        add(tar)
    return buf.getvalue()


def data(tar):
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            path = os.path.join(base, name)
            tar.add(path, arcname="./" + DEST + path[len(ROOT):], filter=clean)


def control(tar):
    files = (("control", "Package: enigma2-plugin-extensions-debridflix\nVersion: %s\nSection: extra\nPriority: optional\n"
              "Architecture: all\nMaintainer: David\nDescription: DebridFlix - Orion and debrid browser/player for Enigma2\n" % VERSION, 0o644),
             ("postrm", "#!/bin/sh\nrm -rf /%s\nexit 0\n" % DEST, 0o755))
    for name, text, mode in files:
        info = tarfile.TarInfo("./" + name)
        blob = text.encode()
        info.size, info.mode, info.mtime = len(blob), mode, int(time.time())
        tar.addfile(clean(info), io.BytesIO(blob))


os.makedirs("dist", exist_ok=True)
out_path = "dist/enigma2-plugin-extensions-debridflix_%s_all.ipk" % VERSION
with open(out_path, "wb") as out:
    out.write(b"!<arch>\n")
    for name, blob in (("debian-binary", b"2.0\n"), ("control.tar.gz", tgz(control)), ("data.tar.gz", tgz(data))):
        out.write(("%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (name, int(time.time()), 0, 0, "100644", len(blob))).encode())
        out.write(blob + (b"\n" if len(blob) % 2 else b""))
print(out_path)
