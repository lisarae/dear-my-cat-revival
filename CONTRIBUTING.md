# Contributing

The usual job is: **a screen freezes, so find which reply was missing something, and teach `server/fakeserver.py` to send it.**

## 1. Find the request

With the server running, reproduce the freeze. The last line in the server window (or in `requests.log`) is usually the culprit, especially if it says `[no special handler, sent plain success]`.

## 2. Find what the game reads from the reply

You need your own copy of the game (see the README). Then:

1. Unpack it. An XAPK and an APK are both zip files.
   - `com.flerogames.AfterRain.apk` → `assets/bin/Data/Managed/Metadata/global-metadata.dat`
   - `config.arm64_v8a.apk` → `lib/arm64-v8a/libil2cpp.so`
2. Run [Il2CppDumper](https://github.com/Perfare/Il2CppDumper) (needs .NET; set `DOTNET_ROLL_FORWARD=Major` on newer .NET versions):
   ```
   dotnet Il2CppDumper.dll libil2cpp.so global-metadata.dat dump
   ```
   This writes `dump/dump.cs` (class and field names) and `dump/script.json` (addresses). The "This file may be protected" warning is harmless.
3. Find the handler. Search `dump.cs` for the endpoint string's purpose. Reply handlers are lambdas that take a `JObject`, for example:
   ```
   grep -n "b__.*(JObject rcv)" dump/dump.cs | grep -i daily
   ```
4. Disassemble it with the game's names filled in:
   ```
   python3 -m pip install capstone pyelftools
   python3 tools/disasm.py --so libil2cpp.so --script dump/script.json "LoadDailyRequestServerData>b__20_0"
   ```
   In the output:
   - `STR "..."` is a JSON key the code uses
   - `JObject$$get_Item` means the key is **required**: if it's missing, the game freezes
   - `JObject$$TryGetValue` means it's optional
   - `ToObject<...>` means the value is turned into a class, so look that class's fields up in `dump.cs`
   - a jump table after `Value<int>` means each number does something different (see `ver/check` in [docs/FINDINGS.md](docs/FINDINGS.md))

## 3. Add a handler

In `server/fakeserver.py`, write a function returning `ok(...)` with the needed keys, and add it to `HANDLERS`. If the game later saves that data (a matching `update`/`cu_` endpoint), store it in `STATE` and `save_state(STATE)` so it comes back at the next login.

Test it with curl before trying it in the game:

```
curl -X POST http://127.0.0.1:19000/daily_quest/get_daily_quest --data 'params={}'
```

Please add what you learn to `docs/FINDINGS.md`.

## Ground rules

- **Never commit game files**: no APK, XAPK, `.so`, metadata or `dump/` output. `.gitignore` covers the usual names.
- Don't commit your `dmc_save.json` or `requests.log`. They hold your save and device details.
- Don't point the game at any server other than your own, including the leftover development addresses inside the game.
