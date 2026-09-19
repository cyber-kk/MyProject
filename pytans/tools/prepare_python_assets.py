#!/usr/bin/env python3
"""
Fetch Termux python3 + dependency .deb packages for aarch64, extract,
rebase prefix (strip /data/data/com.termux/files/usr), prune, resolve
symlinks to copies, and stage into the APK assets dir.

Output: /home/z/my-project/pytans-build/assets/python/   (the new $PREFIX)
        prints python version + layout summary
"""
import gzip
import io
import lzma
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request

BASE = "/home/z/my-project/pytans-build"
DEBS = os.path.join(BASE, "debs")
STAGE = os.path.join(BASE, "stage")          # raw tar extraction (termux paths)
ROOT = os.path.join(BASE, "assets")          # assets root
PYDIR = os.path.join(ROOT, "python")         # new prefix root
REPO = "https://packages.termux.dev/apt/termux-main"
ARCH = "binary-aarch64"

os.makedirs(DEBS, exist_ok=True)
shutil.rmtree(STAGE, ignore_errors=True)
shutil.rmtree(ROOT, ignore_errors=True)
os.makedirs(PYDIR, exist_ok=True)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pytans-builder/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


# ---------- 1. package index ----------
idx_url = REPO + "/dists/stable/main/" + ARCH + "/Packages"
print("fetching index:", idx_url)
try:
    raw = fetch(idx_url)
except Exception:
    raw = lzma.decompress(fetch(idx_url + ".xz"))
if raw[:2] == b"\x1f\x8b":
    raw = gzip.decompress(raw)

packages = {}   # name -> dict(version, filename, deps)
cur = {}
for line in raw.decode("utf-8", "replace").splitlines():
    if not line.strip():
        if cur.get("Package"):
            packages.setdefault(cur["Package"], cur)
        cur = {}
        continue
    if ":" in line:
        k, v = line.split(":", 1)
        cur[k.strip()] = v.strip()
if cur.get("Package"):
    packages.setdefault(cur["Package"], cur)
print("index packages:", len(packages))

# ---------- 2. resolve deps ----------
def dep_names(depstr):
    out = []
    for chunk in depstr.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        first = chunk.split("|")[0].strip()
        name = first.split(" ")[0]
        out.append(name)
    return out

ROOT_PKGS = ["python", "ca-certificates"]
todo = list(ROOT_PKGS)
seen = set()
plan = {}
while todo:
    name = todo.pop(0)
    if name in seen:
        continue
    seen.add(name)
    info = packages.get(name)
    if info is None:
        print("WARN: package not in index:", name)
        continue
    plan[name] = info
    for d in dep_names(info.get("Depends", "")):
        if d not in seen:
            todo.append(d)
print("resolved %d packages:" % len(plan))
for n in sorted(plan):
    print("  ", n, plan[n].get("Version", "?"))

# ---------- 3. download debs ----------
for name, info in sorted(plan.items()):
    url = REPO + "/" + info["Filename"]
    dest = os.path.join(DEBS, os.path.basename(info["Filename"]))
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print("cached:", os.path.basename(dest))
        continue
    print("download:", os.path.basename(dest))
    data = fetch(url)
    with open(dest, "wb") as f:
        f.write(data)

# ---------- 4. extract data.tar.* ----------
for name, info in sorted(plan.items()):
    deb = os.path.join(DEBS, os.path.basename(info["Filename"]))
    members = subprocess.run(["ar", "t", deb], capture_output=True, text=True).stdout.split()
    data_member = [m for m in members if m.startswith("data.tar")]
    if not data_member:
        print("SKIP (no data.tar):", deb)
        continue
    member = data_member[0]
    raw_tar = subprocess.run(["ar", "p", deb, member], capture_output=True).stdout
    if member.endswith(".xz"):
        buf = lzma.decompress(raw_tar)
        mode = "r:"
    elif member.endswith(".gz"):
        buf = gzip.decompress(raw_tar)
        mode = "r:"
    elif member.endswith(".zst"):
        import zstandard
        buf = zstandard.ZstdDecompressor().decompress(raw_tar)
        mode = "r:"
    else:
        buf = raw_tar
        mode = "r:"
    with tarfile.open(fileobj=io.BytesIO(buf), mode=mode) as tf:
        tf.extractall(STAGE)
    print("extracted:", os.path.basename(deb))

# ---------- 5. rebase prefix ----------
usr = os.path.join(STAGE, "data/data/com.termux/files/usr")
if not os.path.isdir(usr):
    # some builds may have ./usr directly
    alt = os.path.join(STAGE, "usr")
    usr = alt if os.path.isdir(alt) else usr
assert os.path.isdir(usr), "termux usr dir not found: " + usr
for entry in os.listdir(usr):
    shutil.move(os.path.join(usr, entry), os.path.join(PYDIR, entry))
print("rebased prefix ->", PYDIR)

# ---------- 6. prune ----------
PRUNE_DIRS = ["include", "share/man", "share/doc", "share/info", "share/locale",
              "lib/pkgconfig", "lib/cmake", "share/pkgconfig", "share/man3"]
for d in PRUNE_DIRS:
    p = os.path.join(PYDIR, d)
    if os.path.isdir(p):
        shutil.rmtree(p)
        print("pruned dir:", d)

import re
pyver = None
for e in os.listdir(os.path.join(PYDIR, "lib")):
    if re.match(r"python3\.\d+$", e):
        pyver = e
print("stdlib dir:", pyver)
stdlib = os.path.join(PYDIR, "lib", pyver)
for d in ["test", "idlelib", "turtledemo", "lib2to3"]:
    p = os.path.join(stdlib, d)
    if os.path.isdir(p):
        shutil.rmtree(p)
        print("pruned stdlib:", d)
# remove __pycache__ everywhere and static libs
for dirpath, dirnames, filenames in os.walk(PYDIR):
    for dn in list(dirnames):
        if dn == "__pycache__":
            shutil.rmtree(os.path.join(dirpath, dn))
            dirnames.remove(dn)
    for fn in filenames:
        if fn.endswith(".a") or fn.endswith(".pyc"):
            os.remove(os.path.join(dirpath, fn))
# prune old .pyo-like/egg stuff not needed; keep site-packages for pip

# ---------- 7. resolve symlinks -> real copies ----------
fixed, dropped = [], []
for dirpath, dirnames, filenames in os.walk(PYDIR):
    for fn in dirnames + filenames:
        p = os.path.join(dirpath, fn)
        if os.path.islink(p):
            target = os.readlink(p)
            if os.path.isabs(target):
                if target.startswith("/data/data/com.termux/files/usr/"):
                    real = os.path.join(PYDIR, target[len("/data/data/com.termux/files/usr/"):])
                else:
                    real = None
            else:
                real = os.path.normpath(os.path.join(dirpath, target))
            if real and os.path.isfile(real) and not os.path.islink(real):
                st = os.stat(real)
                os.unlink(p)
                shutil.copy2(real, p)
                os.chmod(p, st.st_mode)
                fixed.append((os.path.relpath(p, PYDIR), target))
            else:
                os.unlink(p)
                dropped.append((os.path.relpath(p, PYDIR), target))
print("symlinks resolved:", len(fixed), "dropped:", len(dropped))
for n, t in dropped:
    print("  DROPPED:", n, "->", t)

# ---------- 8. summary ----------
def du(path):
    total = 0
    for dp, dns, fns in os.walk(path):
        for f in fns:
            total += os.path.getsize(os.path.join(dp, f))
    return total

print("asset size: %.1f MB" % (du(PYDIR) / 1e6))
key = [
    "bin/python3.13", "bin/python3", "lib/libpython3.13.so.1.0",
    "lib/python3.13/os.py", "lib/python3.13/lib-dynload/_ssl.cpython-313.so",
    "etc/tls/cert.pem", "bin/pip3",
]
print("--- key files ---")
for k in key:
    p = os.path.join(PYDIR, k)
    print(("OK  " if os.path.exists(p) else "MISS"), k)
# find actual _ssl module name
dyn = os.path.join(stdlib, "lib-dynload")
if os.path.isdir(dyn):
    ssls = [f for f in os.listdir(dyn) if f.startswith("_ssl")]
    print("ssl module:", ssls)
    print("dynload count:", len(os.listdir(dyn)))
# python binary type
out = subprocess.run(["file", os.path.join(PYDIR, "bin", "python3.13")], capture_output=True, text=True).stdout
print(out.strip())
# keep python version for later scripts
open(os.path.join(BASE, "pyver.txt"), "w").write(pyver or "")
print("DONE")
