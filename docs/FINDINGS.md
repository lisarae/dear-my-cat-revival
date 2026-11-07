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
  - `8602`, `8603`, `8610`, `8700`: social and help errors
  - any other value: generic server-error popup
- If the reply body is empty, the error callback is used.

**Rule of thumb:** an endpoint handler that reads a key with `JObject[...]` (a required key) and finds it missing throws an exception inside a Unity coroutine. It **does not show an error**. The game simply freezes or stays dimmed. Keys read with `TryGetValue` are optional.

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

## Endpoints not handled yet (generic success reply)

These come from `WAS.ServerAPI`. Some may freeze the screen that uses them:

`withdrawal`, `login_apple`, `user/get_other_user_info`, `insert_logItem`, `insert_log_ads`, `insert_log_switch`, `shop/*`, `aos/validate*`, `ios/validate*`, `inapp/*`, `insert_subItem`, `mailbox/*`, `get_event`, `user_event/*`, `personal_event/*`, `deco/insert_preset`, `deco/get_preset`, `deco/update_preset`, `diamond/restore`, `user_tag/*`, `user/get_other_user_info_by_tag`, `bookmark/*`, `social/*`, `token/*`, `coupon/check`, `req_move_code`, `validate_move_code`, `move_data`, `reset_user_data`

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

After loading: `coupon/state`, `daily_reset/get_daily_reset`, and `daily_quest/get_daily_quest` when daily quests open.
