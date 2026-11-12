# Dear My Cat: Revival

Play **Dear My Cat** (version 2.1.9) again after its official servers shut down.

This project is a small stand-in server that runs on your own computer, plus a patcher that points your copy of the game at it. The game runs in an Android emulator (BlueStacks), talks to the server on your computer, and saves your progress locally.

> **This repository contains no game files.** You download the game yourself (see step 2). The patcher only changes your own copy. This is an unofficial fan project, not affiliated with Flero Games or LikeitGames. All rights to Dear My Cat belong to its owners.

**Status:** loading, cats, decorating, daily quests and saving all work. Setting a nickname and opening the social menu work, however, friends, ranking and helping a friend are untested or may not work. Features that used the online service (shop purchases, mail, events) remain untested. See [docs/FINDINGS.md](docs/FINDINGS.md).

**Tested on:** macOS (Apple Silicon) with BlueStacks Air. Windows should work the same way but hasn't been tested yet. Reports are welcome.

---

## What you need

| Tool | What it's for | Where to get it |
|---|---|---|
| BlueStacks | Android emulator the game runs in | https://www.bluestacks.com |
| Python 3 | Runs the server and the patcher | Mac: comes with Xcode tools or `brew install python`. Windows: https://www.python.org (tick "Add to PATH") |
| Java | Signs the patched game so Android will install it | Mac: `brew install openjdk`. Windows: https://adoptium.net |
| Android platform-tools (`adb`) | Installs the patched game into BlueStacks | https://developer.android.com/tools/releases/platform-tools |
| uber-apk-signer | The signing tool | https://github.com/patrickfav/uber-apk-signer/releases (download the `.jar` under **Assets**) |
| UnityPy (Python package) | Lets the patcher edit one game setting | `python3 -m pip install -r requirements.txt` |

On Windows, type `python` wherever this guide says `python3`.

---

## Setup (once)

### 1. Get this project

Click **Code → Download ZIP** on GitHub and unzip it, or run `git clone` on the repository. Open a terminal (Mac: Terminal; Windows: PowerShell) in the project folder, then install the Python package:

```
python3 -m pip install -r requirements.txt
```

(On a Mac, if pip complains about an "externally managed environment", add `--user`.)

### 2. Download the game

Download **Dear My Cat version 2.1.9** as an XAPK, for example from APKPure:
https://apkpure.net/es/dear-my-cat-relaxing-cat-game/com.flerogames.AfterRain

It must be **2.1.9**, the final version. Keep the original file somewhere safe as your backup.

### 3. Patch it

Put the `uber-apk-signer-*.jar` in the `patcher` folder or your Downloads folder, then run:

```
python3 patcher/patch.py "path/to/Dear My Cat_2.1.9.xapk"
```

The patcher:
- finds your computer's network address (for example `192.168.0.25`)
- writes it into the game
- signs the result

It prints the exact commands to install the game. The patched files go in a `patched` folder.

If it picks the wrong address (for example a VPN address), pass yours with `--ip`:

```
python3 patcher/patch.py "Dear My Cat.xapk" --ip 192.168.0.25
```

To find your address: Mac: System Settings → Wi-Fi → Details. Windows: `ipconfig`, then look for "IPv4 Address".

### 4. Install it into BlueStacks

1. In BlueStacks, open **Settings → Advanced**, turn on **Android Debug Bridge (ADB)** and note the address it shows (e.g. `127.0.0.1:5555`).
2. In your terminal, go to the platform-tools folder and connect:
   ```
   ./adb connect 127.0.0.1:5555
   ./adb devices
   ```
   (Windows: `.\adb.exe` instead of `./adb`.)
3. Run the two install lines the patcher printed (`adb uninstall …` and `adb install-multiple …`). If you already have the original game installed, the uninstall removes it first. Android won't install a patched copy over the original.

If `adb` says **"more than one device/emulator"**, add `-s` and a name from `adb devices`, e.g. `./adb -s emulator-5554 install-multiple …`.

### 5. Make your computer's address stay the same

The game only knows the address it was patched with. If your router gives your computer a new address later, the game will show "Unstable internet connection". To prevent that:
- **Best option:** in your router's settings, reserve (or "always assign") the current address for your computer.
- **Otherwise:** run the patcher again with the new address and reinstall. Your progress is kept in the server's save file.

---

## Playing (every time)

1. **Start the server first**, and leave the window open while you play:
   ```
   python3 server/fakeserver.py
   ```
   The first time, your computer may ask whether to allow incoming connections. Click **Allow**. On Windows, allow it on **Private networks**.
2. Open Dear My Cat in BlueStacks.

The server window shows each request the game makes. Your progress is saved in `server/dmc_save.json`. **Back up that file.**

---

## Troubleshooting

| What you see | Likely cause | Fix |
|---|---|---|
| "Unstable internet connection" popup | The server isn't running, your computer's address changed, or a firewall is blocking it | Start the server. Check that the address it prints matches the one you patched. Allow it through the firewall. |
| You can't tell whether BlueStacks can reach your computer | — | Open Chrome inside BlueStacks and visit `http://YOUR-IP:19000/ping`. You should see a line of text starting with `{"err": 200`. |
| Stuck on a loading screen, or a screen dims and freezes | The server is missing a reply the game needs | Look at the **last line** in the server window, then open an issue (see below). |
| `INSTALL_FAILED_...` while installing | The original game is still installed | `adb uninstall com.flerogames.AfterRain`, then install again. |
| `Failure [INSTALL_FAILED_MEDIA_UNAVAILABLE]` followed by `Success` | adb's fast-install mode failed and it fell back to a normal install | Nothing to fix: it installed. Add `--no-incremental` to skip the message. |
| Patcher says "Unable to locate a Java Runtime" | Java isn't installed or can't be found | Install Java (see the table above). |

### Reporting a problem

Please open an issue with:
- what you did just before it froze or failed
- the **last 10 to 20 lines from the server window**. They show exactly which request went wrong.
- your computer and emulator (e.g. "Mac, BlueStacks Air")

Most fixes so far were a single missing field in one reply. Contributors can work out what's missing from the game's own code: see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## How it works (short version)

- The game used to contact `https://afterrain-live.likeitgamessvc.com`, which no longer exists.
- The patcher replaces that address inside the game with `http://<your computer>:19000/…` and switches on Unity's "allow plain HTTP" setting. It changes nothing else.
- `server/fakeserver.py` answers the game's requests in the format its code expects. That format was worked out by reading the game's compiled code (details in [docs/FINDINGS.md](docs/FINDINGS.md)). Saves the game uploads are kept in `dmc_save.json` and handed back at login.

## License

The code in this repository is released under the MIT License (see [LICENSE](LICENSE)). It does not cover Dear My Cat itself, which you must obtain separately.
