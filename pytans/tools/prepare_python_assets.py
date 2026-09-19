#!/usr/bin/env python3
"""
Fetch Termux python3 + dependency .deb packages for BOTH aarch64 (arm64-v8a)
and arm (armeabi-v7a), extract, rebase prefix (strip
/data/data/com.termux/files/usr), prune, resolve symlinks to copies, and
stage into per-ABI APK asset dirs.

Output layout (Problem-1 fix):
  pytans-build/assets/python/arm64-v8a/       <- $PREFIX tree for arm64
  pytans-build/assets/python/armeabi-v7a/     <- $PREFIX tree for 32-bit arm
  pytans-build/lib/arm64-v8a/libpytanspython.so
  pytans-build/lib/armeabi-v7a/libpytanspython.so
"""
import gzip
import io
import lzma
import os
import re
import shutil
import subprocess
import tarfile
import urllib.request

BASE = "/home/z/my-project/pytans-build"
REPO = "https://packages.termux.dev/apt/termux-main"
DEBS = os.path.join(BASE, "debs")            # debs/<arch>/
STAGE = os.path.join(BASE, "stage")          # stage/<arch>/ (termux paths)
ROOT = os.path.join(BASE, "assets")          # assets root
LIBOUT = os.path.join(BASE, "lib")           # jniLibs staging (launcher stub)

# termux arch -> android ABI
ABI_SPECS = [
    ("aarch64", "arm64-v8a"),
    ("arm", "armeabi-v7a"),
]

ROOT_PKGS = ["python", "ca-certificates"]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pytans-builder/1.1"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def load_index(arch):
    url = REPO + "/dists/stable/main/binary-" + arch + "/Packages"
    print("fetching index:", url)
    try:
        raw = fetch(url)
    except Exception:
        raw = fetch(url + ".xz")
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    elif raw[:6] == b"\xfd7zXZ\x00":
        raw = lzma.decompress(raw)
    packages = {}
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
    print("index [%s] packages: %d" % (arch, len(packages)))
    return packages


def resolve_deps(packages):
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
        for chunk in info.get("Depends", "").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            d = chunk.split("|")[0].strip().split(" ")[0]
            if d and d not in seen:
                todo.append(d)
    return plan


def extract_deb(deb, stage_dir):
    members = subprocess.run(["ar", "t", deb], capture_output=True, text=True).stdout.split()
    data_members = [m for m in members if m.startswith("data.tar")]
    if not data_members:
        print("SKIP (no data.tar):", deb)
        return
    member = data_members[0]
    raw_tar = subprocess.run(["ar", "p", deb, member], capture_output=True).stdout
    if member.endswith(".xz"):
        buf = lzma.decompress(raw_tar)
    elif member.endswith(".gz"):
        buf = gzip.decompress(raw_tar)
    elif member.endswith(".zst"):
        import zstandard
        buf = zstandard.ZstdDecompressor().decompress(raw_tar)
    else:
        buf = raw_tar
    with tarfile.open(fileobj=io.BytesIO(buf), mode="r:") as tf:
        tf.extractall(stage_dir)


PRUNE_DIRS = ["include", "share/man", "share/doc", "share/info", "share/locale",
              "lib/pkgconfig", "lib/cmake", "share/pkgconfig", "share/man3"]
PRUNE_STDLIB = ["test", "idlelib", "turtledemo", "lib2to3"]


def build_tree(arch, abi, packages):
    deb_dir = os.path.join(DEBS, arch)
    stage_dir = os.path.join(STAGE, arch)
    py_dir = os.path.join(ROOT, "python", abi)
    os.makedirs(deb_dir, exist_ok=True)
    os.makedirs(py_dir, exist_ok=True)

    plan = resolve_deps(packages)
    print("[%s] resolved %d packages:" % (abi, len(plan)))
    for n in sorted(plan):
        print("  ", n, plan[n].get("Version", "?"))

    for name, info in sorted(plan.items()):
        url = REPO + "/" + info["Filename"]
        dest = os.path.join(deb_dir, os.path.basename(info["Filename"]))
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print("cached:", os.path.basename(dest))
            continue
        print("download:", os.path.basename(dest))
        data = fetch(url)
        with open(dest, "wb") as f:
            f.write(data)

    shutil.rmtree(stage_dir, ignore_errors=True)
    os.makedirs(stage_dir, exist_ok=True)
    for name, info in sorted(plan.items()):
        deb = os.path.join(deb_dir, os.path.basename(info["Filename"]))
        extract_deb(deb, stage_dir)
        print("extracted:", os.path.basename(deb))

    usr = os.path.join(stage_dir, "data/data/com.termux/files/usr")
    if not os.path.isdir(usr):
        alt = os.path.join(stage_dir, "usr")
        usr = alt if os.path.isdir(alt) else usr
    assert os.path.isdir(usr), "termux usr dir not found: " + usr
    for entry in os.listdir(usr):
        shutil.move(os.path.join(usr, entry), os.path.join(py_dir, entry))
    print("[%s] rebased prefix -> %s" % (abi, py_dir))

    # prune
    for d in PRUNE_DIRS:
        p = os.path.join(py_dir, d)
        if os.path.isdir(p):
            shutil.rmtree(p)
            print("[%s] pruned dir:" % abi, d)

    pyver = None
    for e in os.listdir(os.path.join(py_dir, "lib")):
        if re.match(r"python3\.\d+$", e):
            pyver = e
    print("[%s] stdlib dir:" % abi, pyver)
    assert pyver, "no python3.x stdlib dir found for " + abi
    stdlib = os.path.join(py_dir, "lib", pyver)
    for d in PRUNE_STDLIB:
        p = os.path.join(stdlib, d)
        if os.path.isdir(p):
            shutil.rmtree(p)
            print("[%s] pruned stdlib:" % abi, d)
    for dirpath, dirnames, filenames in os.walk(py_dir):
        for dn in list(dirnames):
            if dn == "__pycache__":
                shutil.rmtree(os.path.join(dirpath, dn))
                dirnames.remove(dn)
        for fn in filenames:
            if fn.endswith(".a") or fn.endswith(".pyc"):
                os.remove(os.path.join(dirpath, fn))

    # resolve symlinks -> real copies
    fixed, dropped = [], []
    for dirpath, dirnames, filenames in os.walk(py_dir):
        for fn in dirnames + filenames:
            p = os.path.join(dirpath, fn)
            if os.path.islink(p):
                target = os.readlink(p)
                if os.path.isabs(target):
                    if target.startswith("/data/data/com.termux/files/usr/"):
                        real = os.path.join(py_dir, target[len("/data/data/com.termux/files/usr/"):])
                    else:
                        real = None
                else:
                    real = os.path.normpath(os.path.join(dirpath, target))
                if real and os.path.isfile(real) and not os.path.islink(real):
                    st = os.stat(real)
                    os.unlink(p)
                    shutil.copy2(real, p)
                    os.chmod(p, st.st_mode)
                    fixed.append((os.path.relpath(p, py_dir), target))
                else:
                    os.unlink(p)
                    dropped.append((os.path.relpath(p, py_dir), target))
    print("[%s] symlinks resolved: %d dropped: %d" % (abi, len(fixed), len(dropped)))
    for n, t in dropped:
        print("  DROPPED:", n, "->", t)

    # launcher stub -> jniLibs (exec from nativeLibraryDir; targetSdk>=29 rule)
    stub = os.path.join(py_dir, "bin", "python3.14")
    assert os.path.isfile(stub), "missing launcher stub " + stub
    libdir = os.path.join(LIBOUT, abi)
    os.makedirs(libdir, exist_ok=True)
    shutil.copy2(stub, os.path.join(libdir, "libpytanspython.so"))
    os.chmod(os.path.join(libdir, "libpytanspython.so"), 0o755)
    print("[%s] launcher stub -> %s" % (abi, os.path.join(libdir, "libpytanspython.so")))

    return py_dir, pyver


def du(path):
    total = 0
    for dp, dns, fns in os.walk(path):
        for f in fns:
            total += os.path.getsize(os.path.join(dp, f))
    return total


def elf_check(path):
    out = subprocess.run(["file", "-b", path], capture_output=True, text=True).stdout.strip()
    return out


def main():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(ROOT, exist_ok=True)

    summary = []
    for arch, abi in ABI_SPECS:
        print("\n========== %s (%s) ==========" % (arch, abi))
        packages = load_index(arch)
        py_dir, pyver = build_tree(arch, abi, packages)
        summary.append((abi, py_dir, pyver))

    print("\n========== SUMMARY ==========")
    for abi, py_dir, pyver in summary:
        print("ABI %s: %.1f MB, stdlib %s" % (abi, du(py_dir) / 1e6, pyver))
        # key files
        keys = [
            "bin/python3.14",
            "lib/libpython3.14.so",
            "lib/%s/os.py" % pyver,
            "lib/%s/lib-dynload" % pyver,
            "etc/tls/cert.pem",
        ]
        for k in keys:
            p = os.path.join(py_dir, k)
            print(("  OK  " if os.path.exists(p) else "  MISS"), k)
        dyn = os.path.join(py_dir, "lib", pyver, "lib-dynload")
        if os.path.isdir(dyn):
            ssls = [f for f in os.listdir(dyn) if f.startswith("_ssl")]
            print("  ssl module:", ssls, "| dynload modules:", len(os.listdir(dyn)))
        print("  python stub ELF:", elf_check(os.path.join(py_dir, "bin", "python3.14")))
        print("  libpython ELF:", elf_check(os.path.join(py_dir, "lib", "libpython3.14.so")))
        print("  jniLib stub ELF:", elf_check(os.path.join(LIBOUT, abi, "libpytanspython.so")))
        # verify .so ABIs match: readelf machine
        so_files = []
        libdir = os.path.join(py_dir, "lib")
        for fn in os.listdir(libdir):
            fp = os.path.join(libdir, fn)
            if os.path.isfile(fp) and fn.endswith(".so"):
                so_files.append(fp)
        machines = set()
        for fp in so_files:
            out = subprocess.run(["readelf", "-h", fp], capture_output=True, text=True).stdout
            m = re.search(r"Machine:\s+(.+)", out)
            c = re.search(r"Class:\s+(.+)", out)
            if m:
                machines.add((c.group(1).strip() if c else "?", m.group(1).strip()))
        print("  ELF machines in lib/:", sorted(machines))

    print("\nDONE")


if __name__ == "__main__":
    main()
