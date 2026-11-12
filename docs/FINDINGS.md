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
| `daily_reset/get_daily_reset` | — | Optional `daily_reset.ddata` object (`DailyResetData`). If absent, the game starts a new day's limits. |
| `daily_reset/update_daily_reset` | — | The request carries `ddata` (JSON text) |
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

## Endpoints not handled yet (generic success reply)

These come from `WAS.ServerAPI`. Some may freeze the screen that uses them:

`withdrawal`, `login_apple`, `user/get_other_user_info`, `insert_logItem`, `insert_log_ads`, `insert_log_switch`, `shop/*`, `aos/validate*`, `ios/validate*`, `inapp/*`, `insert_subItem`, `mailbox/*`, `user_event/*`, `personal_event/*`, `diamond/restore`, `user/get_other_user_info_by_tag`, `social/help_fr`, `user_tag/add_point*`, `user_tag/get_user_tag_idx`, `bookmark/new_bookmark`, `bookmark/delete_bookmark`, `token/*` (except `token/get_season_token`), `coupon/check`, `req_move_code`, `validate_move_code`, `move_data`, `reset_user_data`

The social endpoints still on the generic reply (`user/get_other_user_info_by_tag`, `social/help_fr`, `user_tag/add_point*`, `bookmark/new_bookmark`, `bookmark/delete_bookmark`) have not been tested, so adding a friend, visiting a friend and helping a friend may freeze. Only the nickname setup and opening the social menu have been confirmed to work. The ranking, search and friends screens are replied to with empty lists and have not been checked on screen. The friend code is made up by the server (the first 8 characters of an MD5 of the local GUID, upper-cased); the game does not require that format.

The `insert_log*` endpoints are analytics and are fine with the envelope alone.

## Startup order (BTS loading processors)

1. `DeviceSetting`
2. `NetworkCheck`
3. `PlatformLogin`: `ver/check`, then Firebase, then the Google Play Games sign-in
4. `LoadUserInfo`: if signed in, `deco_info/get_deco` and `login`
5. `ServerNoticeCheck`: fetches `https://kr.object.ncloudstorage.com/af-live/json/maintenance_notice.json`
6. `TableDataLoad`
7. `TermsCheck`
8. `WaitForLoadingAD`

After loading: `deco/get_preset` (once decoration is unlocked), `coupon/state`, `daily_reset/get_daily_reset`, `daily_quest/get_daily_quest` when daily quests open, then `get_event` and `token/get_season_token`.

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
