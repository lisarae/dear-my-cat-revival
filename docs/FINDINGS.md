# What the game expects from its server

Notes from reading the compiled code of Dear My Cat **2.1.9** (Unity 2022.3, IL2CPP, arm64). These notes are the reference for `server/fakeserver.py`.

## Transport

- The base address is `https://afterrain-live.likeitgamessvc.com`. That domain no longer resolves.
  - The game also contains two development servers, `https://cat-dev.wemade-connect.com` and `http://101.101.218.230:19000`. They aren't used by release builds, and this project does not use them.
- Requests are `POST <base>/<endpoint>` with a form body `params=<url-encoded JSON>`.
- Every request includes the common fields from `BaseRequest`: `user_idx`, `guid`, `platformuserid`, `legacyid`, `session_id`, `platformcode` (15) and `oscode` (20).
- The game also calls `GET <base>/ping` to check that it can reach the server.
- Unity's Player Setting `insecureHttpOption` is `0` (HTTP blocked) in the shipped game. The patcher sets it to `2`. Without that change, Unity refuses the request before it is sent (log: `Non-secure network connections disabled in Player Settings`).

## Reply envelope (`WAS.WASPacket.Rcv`)

The reply is parsed as JSON:

- `err` is read as an integer (`WAS_ERROR_CODE`):
  - `200`: success. If `server_time` is present it is passed to `GameTimer.StartServerTime` (parsed with `DateTime.TryParse`, en-US), and then the endpoint's own handler runs.
  - `503`: server maintenance popup
  - `5252`: data failure
  - `6666`: deleted user
  - `20000`: duplicate login
  - `20001`: session expired
  - `8602`, `8603`, `8610`, `8700`: social and help errors. The game has handling for these, but which code means what has **not** been confirmed. `fakeserver.py` uses `8602` for "player not found" in `user_tag/get_user_tag`, which is a guess.
  - any other value: generic server-error popup
- If the reply body is empty, the error callback is used.

**Rule of thumb:** an endpoint handler that reads a key with `JObject[...]` (a required key) and finds it missing throws an exception inside a Unity coroutine. It **does not show an error**. The game simply freezes or stays dimmed. Keys read with `TryGetValue` (or checked with `ContainsKey` first) are optional.

## Requests are sent one at a time

`WASServerClient` keeps a queue (`_packetList`) and a single `_currentPacket`. The next request is sent only after the current one's reply handler finishes. **If a handler crashes on a missing required key, that request never finishes and every later request waits behind it forever.** `GET /ping` uses a separate path, so it keeps arriving every few seconds and the server looks alive.

What this looks like: the server log stops at one request (often one marked UNHANDLED), followed only by `/ping`. The screen that freezes can be far from the request that caused it. For example, a missing `event_info` in `get_event`, called just after loading, froze the level 7 decoration tutorial and a photo mission later on. A reply to `user_tag/make_tag` without `user_tag` froze the nickname screen the moment "Connect" was pressed.

Debugging tip: when the game freezes, look for the **last request that isn't `/ping`**, not just the last line.

Also check that the server you are looking at is the one the game is really talking to. Several freezes during the social work came from running a copy of `fakeserver.py` that had no social handlers, while a newer file sat unused next to it. Run the server with a full path, and look for the startup lines it prints.

The game's own Unity log is silent after startup, so `adb logcat` does not show these exceptions. The server log is the useful one.

## Endpoints the server handles

| Endpoint | Required in reply | Notes |
|---|---|---|
| `ping` | — | Envelope only |
| `ver/check` | `status` (int) | `0` OK. `1` forced update popup. `2` version popup. `3` server check. **A missing key causes a silent freeze on Loading.** |
| `login` | `user` object with `user_idx` (uint), `guid`, `udata` (string) | Optional in `user`: `state` (0 normal, 2 banned, 3 data moved), `reg_date`. Optional at top level: `session_id`, `server_time`, `umoneydata`, `user_update_info`, `sale_event`. `udata == "{}"` keeps the save on the device. Otherwise `udata` is the save as JSON text (`JsonUtility.FromJson`). |
| `user/get_info` | `user.udata`, `umoneydata` object | `umoneydata`: `user_idx`, `umoney_idx`, `inapp_dia`, `free_dia`, `rainbow_coin` |
| `user/update` | — | The request carries `udata` (full save as JSON text), `inapp_dia`, `free_dia` and `rainbow_coin`. The server stores them. |
| `deco_info/get_deco` | `deco` object | Optional `deco.deco_data` (JSON text; `"{}"` means none) |
| `deco_info/update_deco` | — | The request carries `deco_data` and `build_count` |
| `new_session` | — | Optional `session_id` |
| `daily_quest/get_daily_quest` | `daily_quest` | `null` makes the game generate new quests. Otherwise send `{"dq_data": <object>}` (`Daily_GetRespone`). `dq_data` needs a non-zero `forceResetVer` or the game regenerates the quests. **A missing key leaves the screen dimmed after inviting a cat.** |
| `daily_quest/cu_daily_quest` | — | The request carries `dq_data` (JSON text) |
| `daily_reset/get_daily_reset` | — | Optional `daily_reset.ddata` object (`DailyResetData`). If absent, the game starts a new day's limits. `ddata` holds the game's daily limits, including the arcade mini-game plays and their 24h "Time left" window. If the server hands back the stored `ddata`, the game keeps those limits until its own 24h timer runs out (arcade stays at "0 / 3" across restarts). By default `fakeserver.py` drops the stored `ddata` at every `login`, so each game restart starts a new day; **every** limit in `ddata` resets, not only the arcade. Start the server with `--real-daily-reset` to keep `ddata` and let the game's 24h timer decide, like the original server. |
| `daily_reset/update_daily_reset` | — | The request carries `ddata` (JSON text). The server stores it. Keys seen in the log (all booleans): `CheckShop`, `LimitedMainEvent`, `GachaBox`, `DailyRequestQuest`, `MiniGamePlayLimit`, `DreamPictureAdLimit`, `CheckOneDayPackage`. What each flag means has **not** been confirmed. |
| `coupon/state` | — | Optional `status` |
| `user/get_user_platform` | — | Reads `is_user` (only used when changing the platform account) |
| `deco/get_preset` | `preset` (list) | Each item is `DecoPresetServerData`: `preset_idx`, `user_idx`, `slot_idx` (0–5), `pdata` (a `LocalDecoPresetData` **object**, not text, and never null). `[]` means no presets. The game shows a loading overlay before asking and only hides it in this handler, so **a missing key freezes the decoration screen (level 7 tutorial).** Called after loading, from `_CheckDecoPresetServerMatch`, once decoration is unlocked. |
| `deco/insert_preset` | `new_preset_idx` (int) | The request carries `slot_idx` and `pdata` (JSON text of `LocalDecoPresetData`: `name`, `preset_idx`, `theme`, `isOpen`, `decos`, `areaIds`, `pos`, `rot`, `interac`). |
| `deco/update_preset` | — | The request carries `preset_idx` and `pdata` (JSON text). |
| `get_event` | `event_info` (list) | Each item is `ServerEventInfo`: `event_idx`, `event_id`, `type`, `begin_date`, `end_date`. `[]` means no events. Also feeds the shop package lists. **A missing key jams the request queue (see above).** Sent by `EventController._GetEventInfo` about 5 seconds after loading. |
| `token/get_season_token` | — | Optional `season_infos` (list) and `now_season_info` (`SeasonToken_Respone`: `event_id`, `event_start_time`, `event_end_time`, `shop_end_time`, `package_id`). Sent with `get_event`. |
| `user_tag/make_tag` | `user_tag` (object) | Nickname registration. The request carries `name`, `img_id`, `local`, `ver`. The reply `user_tag` is a `Social_UserTag`: `tag_idx`, `user_idx`, `login_date`, `tag` (the friend code), `name`, `img_id`, `local`, `ver`, `point`, `season`, `ranking_point`, `last_rnds`. **A missing `user_tag` freezes the nickname screen.** The game counts the player as registered (`SocialController.get_IsRegistSocialData`) only when the stored `tag` string is non-empty. |
| `user_tag/change_name`, `user_tag/change_img` | — | Envelope only |
| `user_tag/get_user_tag` | `user_tag` (object) | Search for a player by friend code. Used by the search screen. The "not found" error code is not confirmed (see the error list above). |
| `user_tag/get_rnd_tags` | `user_tags` (list) | Random players list. `[]` means none. |
| `social/social_info` | — | Opens the social menu. All keys are optional: `user_tag`, `behelped_infos`, `bookmarks`. The game also reads `help_record`, `user_tags` and `my_point` if present. **Without `user_tag` the game shows the nickname screen again**, so send it whenever a nickname has been saved. |
| `social/get_be_helped_infos`, `social/get_be_helped_infos_by_rnds` | — | Optional `behelped_infos` (list). `[]` means nobody has helped. |
| `social/get_last_season_hallfame` | `hallfame` (list) | Ranking screen. `[]` means no entries. |
| `bookmark/get_bookmarks` | `bookmarks` (list) | Friends list. `[]` means no friends. |
| `user_tag/add_point` (and any `user_tag/add_point*` path) | not confirmed | Sent when Happiness Tree → "Harvest Happiness Berries" is tapped. The request carries `point` and `rnds` (seen: `{"point": 21, "rnds": 1}`). `point` was the "Total yield" the game showed before the tap, so the amount is worked out by the game, not the server; the server cannot change what the player collects. Left on the generic reply, **the screen dims and the request queue jams.** `fakeserver.py` adds `point` to the saved `social_tag.point` and replies with `user_tag` (updated), `point`, `my_point`, `ranking_point` and `season`. This reply is confirmed to work, but which of those keys the game actually requires has **not** been confirmed (the reply handler has not been disassembled yet). |
| `personal_event/new_c_event` | `new_peronal_event` (object) | The Puzzle Event. Each puzzle appears to be its own event with its own `pe_id` (the one tested was 17). The request carries `pe_id`, `pe_data` (the game's `LocalPersonalEventData` as JSON text, `serverIdx` 0 when new) and `period` (seen: 4320). The reply key is spelled `new_peronal_event` in the game. It is a `ServerUserPersonalEventInfo`: `p_idx`, `user_idx`, `pe_id`, `pe_data` (an **object**, not text), `try_count`, `b_get` (a string). Sent every time the screen opens. **The game replaces its own copy of the event with this reply, so the reply must carry the latest saved data; a stale copy erases found pieces.** A missing key makes the game do nothing and show no error: the puzzle cards stay greyed out and tapping one only clicks. See [Puzzle Event](#puzzle-event-personal-events). |
| `personal_event/update` | — | The request carries `p_idx` and `pe_data` (the whole event as JSON text). Sent after every change: a piece found, a box opened, the ad counter. The server stores `pe_data` by `p_idx`. Left on the generic reply, found pieces are lost. |
| `personal_event/get_all_info` | `personal_events` (list) | Sent at every game start; the request has the common fields only. Each item is a `ServerUserPersonalEventInfo` (as above), and **every item needs a non-null `pe_data` object** or the handler crashes. A missing key makes the game load no events, so progress that is saved on the server does not show after a restart. `[]` means no events. |

## Endpoints not handled yet (generic success reply)

These come from `WAS.ServerAPI`. Some may freeze the screen that uses them:

`withdrawal`, `login_apple`, `user/get_other_user_info`, `insert_logItem`, `insert_log_ads`, `insert_log_switch`, `shop/*`, `aos/validate*`, `ios/validate*`, `inapp/*`, `insert_subItem`, `mailbox/*`, `user_event/*`, the other `personal_event/*` endpoints (`c_event`, `finish`, `reopen`, `get_today_event`, `get_event_p_idx`), `diamond/restore`, `user/get_other_user_info_by_tag`, `social/help_fr`, `user_tag/get_user_tag_idx`, `bookmark/new_bookmark`, `bookmark/delete_bookmark`, `token/*` (except `token/get_season_token`), `coupon/check`, `req_move_code`, `validate_move_code`, `move_data`, `reset_user_data`

The social endpoints still on the generic reply (`user/get_other_user_info_by_tag`, `social/help_fr`, `bookmark/new_bookmark`, `bookmark/delete_bookmark`) have not been tested, so adding a friend, visiting a friend and helping a friend may freeze. Only the nickname setup and opening the social menu have been confirmed to work. The ranking, search and friends screens are replied to with empty lists and have not been checked on screen. The friend code is made up by the server (the first 8 characters of an MD5 of the local GUID, upper-cased); the game does not require that format.

The `insert_log*` endpoints are analytics and are fine with the envelope alone.

## Shop and Package: the Google Play check (client-side patch)

Tapping **Shop** or **Package** showed the popup "Unable to access Google Play account information". **No request reached the server** (no `shop/*` or `inapp/*` lines in `requests.log`), so no server reply can fix this. Being signed in to the Play Store in BlueStacks did not help.

Call chain (read from `dump.cs` and `tools/disasm.py`):

- `ShopManager.OpenShopUI` calls `ShopManager.IsStoreInitialized`.
- `IsStoreInitialized` returns true only if `InAppManager.IsInitialized()` is true (the Unity IAP store loaded more than 0 products) or `Main.buildType == 0` (Dev build).
- Otherwise `OpenShopUI` shows the popup (localisation keys `local_shop_open_error_title` / `local_shop_open_error_init_store_aos`).

`IsStoreInitialized` has three callers, so one patch covers all three:

- `ShopManager.OpenShopUI`
- `MenuPackageNoticeButton.OnClickBtnOpenPackage`
- `PackageAlarmUI.OnClickBtnOpenPackage`

The patch (in `patcher/patch.py`): `lib/arm64-v8a/libil2cpp.so`, which is in the arm64 split APK (`config.arm64_v8a.apk`) of the XAPK, not in the main APK. 8 bytes at **file offset `0x1FA635C`** (virtual address `0x1FAA35C`), the start of `ShopManager.IsStoreInitialized`:

| | Bytes | Instructions |
|---|---|---|
| Original | `fe0f1ef8 f44f01a9` | `str x30,[sp,#-0x20]!` ; `stp x20,x19,[sp,#0x10]` |
| Patched | `20008052 c0035fd6` | `mov w0,#1` ; `ret` |

The patcher checks the original bytes first and stops if they differ (a different game version). The offsets are for **2.1.9 arm64 only**.

Result: confirmed that Shop and Package open. Limits:

- Real-money purchases still cannot work: `InAppManager.BuyProduct` has its own `IsInitialized` check.
- Items normally priced by Google Play may show no price.

## Puzzle Event (personal events)

The Puzzle Event screen uses the `personal_event/*` endpoints. The endpoint names were listed from `global-metadata.dat`: `c_event`, `new_c_event`, `update`, `get_all_info`, `get_today_event`, `get_event_p_idx`, `reopen` and `finish`. The replies were read from the game's code (`PersonalPuzzleEventInfoBtn.<_DoOpenPuzzleEvent>b__23_1` reads `new_peronal_event`; `PersonalEventController.<_LoadPersonalEventData>b__17_0` reads `personal_events`) and checked against `requests_full.log`.

How it works, as seen in the log:

- Each puzzle appears to be its own event with its own `pe_id`. The game also created dozens of other events in one burst of `new_c_event` requests (ids 1 to 67 were seen). It sends `update` with `oneDayAdLimit` set to `"10"` right after each creation.
- `pe_data` is text in requests and an object in replies. Its fields (`LocalPersonalEventData`) are `serverIdx`, `id`, `puzzleInfoList` (the found piece ids as strings, for example `["8"]`), `tryCount`, `fixedEpicCounts`, `canOpenFreeBox`, `oneDayAdLimit`, `canGetReward`, `endGetReward` and `isOpen`.
- Opening a box sends `update`, plus the usual `user/update` and `insert_logItem`. Nothing else reaches the server, so what a box contains appears to be decided by the game, not the server. A Silver Box can give something other than a puzzle piece.

What went wrong while these were unhandled, in the order it was found:

1. `new_c_event` on the generic reply: the puzzle cards were greyed out, and tapping one only made a click sound. No request was sent.
2. `new_c_event` replying with the *first* copy of the event every time: found pieces vanished whenever the screen was reopened. The game replaced its copy with the stale reply and then sent that copy back in its next `update`.
3. `update` on the generic reply: the server kept nothing.
4. `get_all_info` on the generic reply: the server had the pieces, but the game started with no events and forgot them after a restart.

`fakeserver.py` keeps every event in `dmc_save.json` under `personal_events`. The first time it sees a `pe_id`, it keeps the id and data the game already has if the game sends them, and otherwise gives the next free `p_idx`. After that, `update` stores the data, and `new_c_event` and `get_all_info` return the stored copy.

Confirmed on screen: the puzzle cards open, a piece from an ad box (`oneDayAdLimit` went from `"10"` to `"9"`) was saved, and it was still there after reopening the screen and after restarting the game.

Not confirmed:

- What `b_get`, `try_count`, `period` (probably minutes), `fixedEpicCounts`, `canOpenFreeBox` and `canGetReward` mean. The server sends `b_get` as `"0"` (a guess) and never changes the others.
- What `personal_event/c_event`, `finish`, `reopen`, `get_today_event` and `get_event_p_idx` do. They have not been seen in the log, so they stay on the generic reply. Event expiry and the reward for finishing a puzzle are not handled.
- `user_event/get_user_event` and `user_event/cu_user_event` look like a separate event system and have not been looked at.

## Startup order (BTS loading processors)

1. `DeviceSetting`
2. `NetworkCheck`
3. `PlatformLogin`: `ver/check`, then Firebase, then the Google Play Games sign-in
4. `LoadUserInfo`: if signed in, `deco_info/get_deco` and `login`
5. `ServerNoticeCheck`: fetches `https://kr.object.ncloudstorage.com/af-live/json/maintenance_notice.json`
6. `TableDataLoad`
7. `TermsCheck`
8. `WaitForLoadingAD`

After loading: `deco/get_preset` (once decoration is unlocked), `coupon/state`, `daily_reset/get_daily_reset`, `daily_quest/get_daily_quest` when daily quests open, then `get_event` and `token/get_season_token`. The game also sends `personal_event/get_all_info` at start (its place in this order was not checked).

## How the replies were found

The keys above come from the compiled game, not from guessing. Guessing failed more than once: guessed `get_event` keys did not match, and a nickname sent as a plain string where the game wanted an object froze the screen.

1. Get `libil2cpp.so` (arm64) and `global-metadata.dat` out of the APK/XAPK.
2. Run [Il2CppDumper](https://github.com/Perfare/Il2CppDumper) on them. It writes `dump.cs` (every class and field, e.g. `Social_UserTag`) and `script.json` (method and string names with addresses).
3. Find the callback for the request. Reply handlers are compiler-generated methods named like `<LoadSocialInfos>b__0`, inside the screen's class.
4. Disassemble it with `tools/disasm.py`: python3 tools/disasm.py --so libil2cpp.so --script script.json "SocialController" --max 400

The output labels the string literals and calls. Look at the JSON keys and how each is read:
   - a call to `JObject$$get_Item` is a **required** key: if it is missing, the game freezes
   - a call to `JObject$$TryGetValue` or `ContainsKey` is an **optional** key
   - `ToObject<...>` names the class the value must fit, so look that class up in `dump.cs` for the field names and types
5. Teach the server to send exactly those keys, then test with `curl` before testing in the game.

Tip: to see which endpoint names the game knows for a feature, run `strings -a global-metadata.dat | grep personal_event` (change the word for another feature). The file is one very long line, so the endpoint list is the last line printed, with stray punctuation between the names.
