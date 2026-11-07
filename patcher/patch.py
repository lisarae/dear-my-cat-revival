#!/usr/bin/env python3
"""
Dear My Cat revival patcher.

Takes YOUR OWN copy of the Dear My Cat 2.1.9 XAPK and makes an installable
copy that talks to the local stand-in server (server/fakeserver.py) instead of
the shut-down official server.

What it changes (nothing else is touched):
  1. The server address baked into the game
     https://afterrain-live.likeitgamessvc.com  ->  http://<your-ip>:<port>/xxx...
  2. Unity's "Allow downloads over HTTP" setting (off -> always allowed),
     so the game may talk to a plain-http server.
  3. Removes the old signature and re-signs both APK parts with one debug key
     (uber-apk-signer), which Android requires before it will install them.

Usage:
  python3 patch.py "Dear My Cat_2.1.9_APKPure.xapk"
  python3 patch.py game.xapk --ip 192.168.1.50 --port 19000 --out patched
  python3 patch.py game.xapk --signer ~/Downloads/uber-apk-signer-1.3.0.jar
"""
import argparse
import glob
import os
import shutil
import socket
import subprocess
import sys
import zipfile

OLD_URL = b"https://afterrain-live.likeitgamessvc.com"
METADATA = "assets/bin/Data/Managed/Metadata/global-metadata.dat"
GGM = "assets/bin/Data/globalgamemanagers"
PACKAGE = "com.flerogames.AfterRain"
EXPECTED_VERSION = "2.1.9"


def fail(msg):
    print("\nERROR: " + msg)
    sys.exit(1)


def guess_ip():
    """The address other devices on your network use to reach this computer."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no traffic is actually sent
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def build_url(ip, port):
    base = "http://%s:%d/" % (ip, port)
    if len(base) > len(OLD_URL):
        fail("Address %s is too long to fit in the game file." % base)
    # The replacement must be exactly as long as the original text; the extra
    # length becomes a dummy folder name ("xxxx") that fakeserver.py ignores.
    return (base + "x" * (len(OLD_URL) - len(base))).encode()


def is_signature(name):
    return name == "META-INF/MANIFEST.MF" or (
        name.startswith("META-INF/") and name.endswith((".SF", ".RSA", ".DSA", ".EC"))
    )


def patch_ggm(data):
    try:
        import UnityPy
    except ImportError:
        fail("UnityPy is not installed. Run:  python3 -m pip install UnityPy")
    env = UnityPy.load(data)
    found = False
    for obj in env.objects:
        if obj.type.name == "PlayerSettings":
            tree = obj.read_typetree()
            if "insecureHttpOption" not in tree:
                fail("This copy of the game has no insecureHttpOption setting. Is it version %s?" % EXPECTED_VERSION)
            tree["insecureHttpOption"] = 2
            obj.save_typetree(tree)
            found = True
    if not found:
        fail("Could not find the game's PlayerSettings.")
    out = bytes(env.file.save())
    for obj in UnityPy.load(out).objects:
        if obj.type.name == "PlayerSettings":
            if obj.read_typetree()["insecureHttpOption"] != 2:
                fail("Changing the HTTP setting did not stick.")
    print("  - allowed plain-http connections")
    return out


def patch_base_apk(src_bytes_or_path, dst, new_url):
    with zipfile.ZipFile(src_bytes_or_path) as zin, zipfile.ZipFile(dst, "w") as zout:
        names = set(zin.namelist())
        if METADATA not in names or GGM not in names:
            fail("This does not look like the Dear My Cat game APK.")
        for item in zin.infolist():
            n = item.filename
            if is_signature(n):
                continue
            data = zin.read(n)
            if n == METADATA:
                count = data.count(OLD_URL)
                if count == 0:
                    fail("Server address not found. Is this the original, unpatched version %s?" % EXPECTED_VERSION)
                data = data.replace(OLD_URL, new_url)
                print("  - redirected the server address (%d places)" % count)
            elif n == GGM:
                data = patch_ggm(data)
            zout.writestr(item, data, compress_type=item.compress_type)


def find_signer(explicit):
    if explicit:
        return explicit if os.path.exists(explicit) else None
    here = os.path.dirname(os.path.abspath(__file__))
    patterns = [
        os.path.join(here, "uber-apk-signer*.jar"),
        os.path.join(os.getcwd(), "uber-apk-signer*.jar"),
        os.path.join(os.path.expanduser("~"), "Downloads", "uber-apk-signer*.jar"),
    ]
    for p in patterns:
        hits = sorted(glob.glob(p))
        if hits:
            return hits[-1]
    return None


def find_java():
    candidates = []
    try:
        brew = subprocess.run(["brew", "--prefix", "openjdk"], capture_output=True, text=True)
        if brew.returncode == 0:
            candidates.append(os.path.join(brew.stdout.strip(), "bin", "java"))
    except OSError:
        pass
    if os.environ.get("JAVA_HOME"):
        candidates.append(os.path.join(os.environ["JAVA_HOME"], "bin", "java"))
    candidates.append(shutil.which("java"))
    for c in candidates:
        if c and os.path.exists(c):
            try:
                if subprocess.run([c, "-version"], capture_output=True).returncode == 0:
                    return c
            except OSError:
                pass
    return None


def main():
    ap = argparse.ArgumentParser(description="Patch Dear My Cat to use a local server.")
    ap.add_argument("game", help="the .xapk (or the main .apk) you downloaded")
    ap.add_argument("--ip", help="this computer's local network address (auto-detected if left out)")
    ap.add_argument("--port", type=int, default=19000, help="server port (default 19000)")
    ap.add_argument("--out", default="patched", help="output folder (default: patched)")
    ap.add_argument("--signer", help="path to uber-apk-signer .jar (searched for if left out)")
    args = ap.parse_args()

    if not os.path.exists(args.game):
        fail("File not found: %s" % args.game)

    ip = args.ip or guess_ip()
    if not ip or ip.startswith("127."):
        fail("Could not work out this computer's network address. Pass it with --ip (e.g. --ip 192.168.0.25).")
    new_url = build_url(ip, args.port)
    print("Server address for the game: %s" % new_url.decode())

    if os.path.isdir(args.out):
        shutil.rmtree(args.out)
    os.makedirs(args.out)
    unsigned = os.path.join(args.out, "unsigned")
    os.makedirs(unsigned)

    print("Patching...")
    if zipfile.is_zipfile(args.game) and any(
        n.endswith(".apk") for n in zipfile.ZipFile(args.game).namelist()
    ):
        # XAPK: a zip holding the main APK plus split APKs
        with zipfile.ZipFile(args.game) as x:
            apks = [n for n in x.namelist() if n.endswith(".apk") and "/" not in n]
            base = PACKAGE + ".apk"
            if base not in apks:
                fail("Could not find %s inside the XAPK." % base)
            for n in apks:
                tmp = os.path.join(unsigned, "_src_" + n)
                with x.open(n) as src, open(tmp, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                if n == base:
                    patch_base_apk(tmp, os.path.join(unsigned, n), new_url)
                    os.remove(tmp)
                else:
                    os.replace(tmp, os.path.join(unsigned, n))
    else:
        patch_base_apk(args.game, os.path.join(unsigned, PACKAGE + ".apk"), new_url)
        print("  (single APK given: if your copy came as an XAPK, use the XAPK instead)")

    print("Signing...")
    signer = find_signer(args.signer)
    java = find_java()
    if not signer or not java:
        print("\nPatched but NOT signed yet: %s" % ("uber-apk-signer .jar not found" if not signer else "Java not found"))
        print("See README step 'Install the tools', then run:")
        print('  java -jar uber-apk-signer-1.3.0.jar --apks "%s" --allowResign --out "%s"' % (unsigned, args.out))
        sys.exit(2)
    r = subprocess.run([java, "-jar", signer, "--apks", unsigned, "--allowResign", "--out", args.out],
                       capture_output=True, text=True)
    signed = sorted(glob.glob(os.path.join(args.out, "*-aligned-debugSigned.apk")))
    if r.returncode != 0 or not signed:
        print(r.stdout[-3000:])
        print(r.stderr[-3000:])
        fail("Signing failed (output above).")
    shutil.rmtree(unsigned)
    for f in glob.glob(os.path.join(args.out, "*.idsig")):
        os.remove(f)

    print("\nDone. Signed files in %s:" % os.path.abspath(args.out))
    for s in signed:
        print("  " + os.path.basename(s))
    print("\nInstall into the emulator (see README):")
    print("  adb uninstall %s" % PACKAGE)
    print('  adb install-multiple --no-incremental %s' % " ".join('"%s"' % os.path.abspath(s) for s in signed))
    print("\nThen start the server:  python3 server/fakeserver.py")
    print("If this computer's address changes from %s, run this patch again." % ip)


if __name__ == "__main__":
    main()
