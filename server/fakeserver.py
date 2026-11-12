"""
fakeserver.py - stand-in server for Dear My Cat 2.1.9, built from the game's own code.
(Includes the social / nickname handlers, user_tag/add_point (the Happiness Tree
 harvest button), and daily limits that start fresh on every game login.)

Run:   python3 server/fakeserver.py              (port 19000, saves next to this file)
       python3 server/fakeserver.py --port 19000 --data-dir ~/DearMyCatSave
Stop:  Ctrl+C

Needs only Python 3 (no extra packages). Keep it running while you play.

What the game's code expects (found by disassembling version 2.1.9):
  * Every reply:   {"err": 200, "server_time": "..."}   200 = success.
  * ver/check:     top-level "status": 0 = OK (1 = update, 2 = popup, 3 = maintenance).
                   Without "status" the game hits an error and freezes on Loading.
  * login:         "user": {user_idx, guid, udata, state, reg_date}, plus
                   optional session_id / umoneydata. state 0 = normal (2 = banned).
  * user/get_info: "user": {udata}, "umoneydata": {...}
  * deco_info/get_deco: "deco": {"deco_data": "..."}
  * deco/get_preset:    "preset": [] (list of saved decoration presets).
                        Without it the decoration screen (level 7) freezes.
  * deco/insert_preset: "new_preset_idx": <int>
  * get_event:          "event_info": [] (list of running events).
                        Without it the game's request queue jams (see below).
  * user_tag/make_tag:  the nickname OK button. "user_tag" REQUIRED (a Social_UserTag
                        object). Without it the game's callback crashes and the request
                        queue jams (screen stays dimmed, nothing else is sent).
  * user_tag/get_user_tag REQUIRES "user_tag" (object), user_tag/get_rnd_tags REQUIRES
    "user_tags" (array), bookmark/get_bookmarks REQUIRES "bookmarks" (array),
    social/get_last_season_hallfame REQUIRES "hallfame" (array).
    social/social_info keys are all optional (user_tag, behelped_infos, bookmarks).
    Your nickname profile is kept in dmc_save.json under "social_tag".
  * user_tag/add_point: sent when Happiness Berries are harvested (request: point, rnds).
                        Unhandled, the screen dims and the request queue jams. The reply
                        carries the updated "user_tag" plus point / my_point / ranking_point /
                        season. Which of those the game REQUIRES was not confirmed, so all
                        are sent. The amount (e.g. 21) is worked out by the game itself.
  * daily_reset/*:      the game's daily limits (arcade plays, the 24h "Time left"
                        countdown) are stored in "ddata". The server forgets them at every
                        login, so restarting the game starts a new day. Use
                        --real-daily-reset to keep them for the game's own 24h timer.
  * udata / deco_data are the game's save files as JSON text; "{}" means "nothing
    stored on the server, keep the save on the device".

Saves the game uploads (user/update, deco_info/update_deco, daily quests...) are
kept in dmc_save.json in the data folder (default: next to this file) and handed back on the next login, so progress
survives reinstalls as long as you keep that file.
Every request is printed and appended to requests.log in the same folder;
requests_full.log has the same requests and replies without truncation.
A request marked >>> UNHANDLED <<< got a generic reply; if the game freezes,
that is usually the place to look (see CONTRIBUTING.md).

The game sends requests one at a time from a queue. If a reply is missing a
required key, the game's handler crashes, that request never finishes, and
every later request waits behind it forever (only /ping still gets through).
So a freeze can show up on a screen far away from the request that caused it.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

_ap = argparse.ArgumentParser(description="Stand-in server for Dear My Cat")
_ap.add_argument("--port", type=int, default=19000)
_ap.add_argument("--data-dir", default=os.path.dirname(os.path.abspath(__file__)),
                 help="folder for dmc_save.json and requests.log")
_ap.add_argument("--real-daily-reset", action="store_true",
                 help="keep daily limits (arcade plays...) until the game's own 24h timer "
                      "runs out, like the original server. Default: every game restart "
                      "(login) starts a fresh day.")
ARGS = _ap.parse_args()

PORT = ARGS.port
DATA_DIR = os.path.abspath(os.path.expanduser(ARGS.data_dir))
os.makedirs(DATA_DIR, exist_ok=True)
LOGFILE = os.path.join(DATA_DIR, "requests.log")
FULLLOG = os.path.join(DATA_DIR, "requests_full.log")
SAVEFILE = os.path.join(DATA_DIR, "dmc_save.json")
# The patcher pads the game's server address with a dummy folder of x's.
PADDING = re.compile(r"^/x+(?=/)")

USER_IDX = 1
GUID = "local-player-0001"
SESSION = "local-session-0001"


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ---------- saved state ----------
def load_state():
    try:
        with open(SAVEFILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {
            "udata": "{}",
            "deco_data": "{}",
            "inapp_dia": 0,
            "free_dia": 0,
            "rainbow_coin": 0,
            "reg_date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        }


def save_state(state):
    tmp = SAVEFILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, SAVEFILE)


STATE = load_state()
if not isinstance(STATE.get("presets", {}), dict):   # early test builds stored a list
    STATE["presets"] = {}


def ok(**extra):
    reply = {"err": 200, "message": "succ", "server_time": now()}
    reply.update(extra)
    return reply


def money():
    return {
        "user_idx": USER_IDX,
        "umoney_idx": 1,
        "inapp_dia": STATE.get("inapp_dia", 0),
        "free_dia": STATE.get("free_dia", 0),
        "rainbow_coin": STATE.get("rainbow_coin", 0),
    }


def user_obj():
    return {
        "user_idx": USER_IDX,
        "guid": GUID,
        "udata": STATE.get("udata", "{}") or "{}",
        "state": 0,
        "reg_date": STATE.get("reg_date", "2026-01-01 00:00:00"),
    }


# ---------- endpoint handlers (params = the JSON the game sent) ----------
def h_ping(p):
    return ok()


def h_ver_check(p):
    return ok(status=0)


def h_login(p):
    # daily_reset/ddata holds the game's daily limits (arcade plays left, the 24h
    # "Time left" countdown...). The original server only reset them once a day.
    # By default we forget them at each login, so restarting the game = a new day.
    if not ARGS.real_daily_reset and "ddata" in STATE:
        STATE.pop("ddata", None)
        save_state(STATE)
    return ok(session_id=SESSION, user=user_obj(), umoneydata=money())


def h_get_info(p):
    return ok(user=user_obj(), umoneydata=money())


def h_user_update(p):
    if isinstance(p.get("udata"), str) and p["udata"]:
        STATE["udata"] = p["udata"]
    for k in ("inapp_dia", "free_dia", "rainbow_coin"):
        if isinstance(p.get(k), int):
            STATE[k] = p[k]
    save_state(STATE)
    return ok()


def h_get_deco(p):
    return ok(deco={"deco_data": STATE.get("deco_data", "{}") or "{}"})


def h_update_deco(p):
    if isinstance(p.get("deco_data"), str) and p["deco_data"]:
        STATE["deco_data"] = p["deco_data"]
        save_state(STATE)
    return ok()


def h_new_session(p):
    return ok(session_id=SESSION)


def h_platform(p):
    return ok(is_user=0)


def _as_json(text):
    """Saved strings go back to the game as JSON objects (or null if none)."""
    if not isinstance(text, str) or not text or text == "{}":
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def h_get_daily_quest(p):
    # The game requires "daily_quest". null -> it generates fresh quests;
    # otherwise {"dq_data": <the quest list it saved earlier>}.
    dq = _as_json(STATE.get("dq_data"))
    return ok(daily_quest=({"daily_quest_idx": 1, "user_idx": USER_IDX, "dq_data": dq} if dq else None))


def h_save_daily_quest(p):
    if isinstance(p.get("dq_data"), str) and p["dq_data"]:
        STATE["dq_data"] = p["dq_data"]
        save_state(STATE)
    return ok()


def h_get_daily_reset(p):
    dd = _as_json(STATE.get("ddata"))
    return ok(daily_reset={"ddata": dd}) if dd else ok()


def h_save_daily_reset(p):
    if isinstance(p.get("ddata"), str) and p["ddata"]:
        STATE["ddata"] = p["ddata"]
        save_state(STATE)
    return ok()


def h_coupon_state(p):
    return ok(status=0)


# ---------- decoration presets ----------
# deco/get_preset reply: "preset" REQUIRED, a list of DecoPresetServerData:
#   {preset_idx, user_idx, slot_idx (0-5), pdata (an OBJECT, never null)}.
#   The game shows a loading overlay before asking and only hides it here.
# deco/insert_preset: request slot_idx + pdata (JSON text); reply "new_preset_idx" REQUIRED.
# deco/update_preset: request preset_idx + pdata (JSON text); reply envelope only.
def _presets():
    return STATE.setdefault("presets", {})   # {"<preset_idx>": {"slot_idx": n, "pdata": {...}}}


def _parse_pdata(p):
    pd = p.get("pdata")
    if isinstance(pd, str):
        try:
            pd = json.loads(pd)
        except ValueError:
            pd = None
    return pd if isinstance(pd, dict) else None


def h_get_preset(p):
    out = []
    for idx, entry in sorted(_presets().items(), key=lambda kv: int(kv[0])):
        slot = entry.get("slot_idx")
        if isinstance(entry.get("pdata"), dict) and isinstance(slot, int) and 0 <= slot <= 5:
            out.append({"preset_idx": int(idx), "user_idx": USER_IDX,
                        "slot_idx": slot, "pdata": entry["pdata"]})
    return ok(preset=out)


def h_insert_preset(p):
    presets = _presets()
    slot = p.get("slot_idx") if isinstance(p.get("slot_idx"), int) else 0
    # one preset per slot: reuse that slot's number if it already exists
    idx = next((int(k) for k, v in presets.items() if v.get("slot_idx") == slot), None)
    if idx is None:
        idx = max([int(k) for k in presets] + [0]) + 1
    presets[str(idx)] = {"slot_idx": slot, "pdata": _parse_pdata(p) or {}}
    save_state(STATE)
    return ok(new_preset_idx=idx)


def h_update_preset(p):
    presets = _presets()
    idx = p.get("preset_idx")
    pd = _parse_pdata(p)
    if isinstance(idx, int) and str(idx) in presets and pd is not None:
        presets[str(idx)]["pdata"] = pd
        save_state(STATE)
    return ok()


# ---------- events ----------
# get_event reply: "event_info" REQUIRED, a list of ServerEventInfo
#   {event_idx, event_id, type, begin_date, end_date}. [] = no events running.
def h_get_event(p):
    return ok(event_info=[])


# token/get_season_token: "season_infos" / "now_season_info" are optional.
def h_season_token(p):
    return ok()


# ---------- social: nickname / profile (formats read from the game's code) ----------
def err_reply(code, message="error"):
    return {"err": code, "message": message, "server_time": now()}


def _my_tag():
    t = STATE.get("social_tag")
    return t if isinstance(t, dict) else None


def _tag_code():
    """A stable 8-character profile code for this local player."""
    return hashlib.md5(GUID.encode()).hexdigest()[:8].upper()


def _int(v, default=0):
    return v if isinstance(v, int) and not isinstance(v, bool) else default


def h_make_tag(p):
    """user_tag/make_tag: the nickname OK button (first time).
    The game REQUIRES "user_tag" as a Social_UserTag object in the reply."""
    t = _my_tag() or {
        "tag_idx": 1,
        "user_idx": USER_IDX,
        "tag": _tag_code(),
        "point": 0,
        "season": 1,
        "ranking_point": 0,
        "last_rnds": 0,
    }
    name = p.get("name")
    t["name"] = name.strip()[:12] if isinstance(name, str) and name.strip() else "Player"
    t["img_id"] = _int(p.get("img_id"))
    t["local"] = _int(p.get("local"))
    t["ver"] = p["ver"] if isinstance(p.get("ver"), str) and p["ver"] else "2.1.9"
    t["login_date"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    STATE["social_tag"] = t
    save_state(STATE)
    return ok(user_tag=t)


def h_change_name(p):
    """user_tag/change_name: success only (the game charges the cost itself)."""
    t = _my_tag()
    name = p.get("name")
    if t and isinstance(name, str) and name.strip():
        t["name"] = name.strip()[:12]
        save_state(STATE)
    return ok()


def h_change_img(p):
    """user_tag/change_img: success only."""
    t = _my_tag()
    if t and isinstance(p.get("img_id"), int):
        t["img_id"] = p["img_id"]
        save_state(STATE)
    return ok()


def h_social_info(p):
    """social/social_info: every key is optional. No user_tag = not registered
    yet, so the game shows the nickname screen."""
    reply = ok()
    t = _my_tag()
    if t:
        reply["user_tag"] = t
        reply["behelped_infos"] = []
        reply["bookmarks"] = []
    return reply


def h_be_helped(p):
    """social/get_be_helped_infos(_by_rnds): optional array, nobody has helped."""
    return ok(behelped_infos=[])


def h_hallfame(p):
    """social/get_last_season_hallfame: the game REQUIRES "hallfame" (array)."""
    return ok(hallfame=[])


def h_get_bookmarks(p):
    """bookmark/get_bookmarks: the game REQUIRES "bookmarks" (array)."""
    return ok(bookmarks=[])


def h_get_user_tag(p):
    """user_tag/get_user_tag: search a player by profile code. The game REQUIRES
    "user_tag" (object) on success. Only you exist, so anyone else is 'not found'.
    8602 is a guess among the social error codes (8602, 8603, 8610, 8700)."""
    t = _my_tag()
    wanted = p.get("tag")
    if t and isinstance(wanted, str) and wanted.strip().upper() == t["tag"]:
        return ok(user_tag=t)
    return err_reply(8602, "user not found")


def h_get_rnd_tags(p):
    """user_tag/get_rnd_tags: random players. The game REQUIRES "user_tags" (array)."""
    return ok(user_tags=[])


def h_add_point(p):
    """user_tag/add_point: sent when you harvest Happiness Berries (request: point, rnds).
    Which key the game requires back was NOT confirmed from its code, so this sends
    the updated profile under every name the social code is known to read."""
    t = _my_tag()
    add = _int(p.get("point"))
    if t is None:
        return ok(point=add, my_point=add)
    t["point"] = _int(t.get("point")) + add
    save_state(STATE)
    return ok(user_tag=t, point=t["point"], my_point=t["point"],
              ranking_point=_int(t.get("ranking_point")), season=_int(t.get("season"), 1))


HANDLERS = {
    "/ping": h_ping,
    "/ver/check": h_ver_check,
    "/login": h_login,
    "/user/get_info": h_get_info,
    "/user/update": h_user_update,
    "/deco_info/get_deco": h_get_deco,
    "/deco_info/update_deco": h_update_deco,
    "/new_session": h_new_session,
    "/user/get_user_platform": h_platform,
    "/daily_quest/get_daily_quest": h_get_daily_quest,
    "/daily_quest/cu_daily_quest": h_save_daily_quest,
    "/daily_reset/get_daily_reset": h_get_daily_reset,
    "/daily_reset/update_daily_reset": h_save_daily_reset,
    "/coupon/state": h_coupon_state,
    "/deco/get_preset": h_get_preset,
    "/deco/insert_preset": h_insert_preset,
    "/deco/update_preset": h_update_preset,
    "/get_event": h_get_event,
    "/token/get_season_token": h_season_token,
    # social
    "/user_tag/make_tag": h_make_tag,
    "/user_tag/change_name": h_change_name,
    "/user_tag/change_img": h_change_img,
    "/user_tag/get_user_tag": h_get_user_tag,
    "/user_tag/get_rnd_tags": h_get_rnd_tags,
    "/social/social_info": h_social_info,
    "/social/get_be_helped_infos": h_be_helped,
    "/social/get_be_helped_infos_by_rnds": h_be_helped,
    "/social/get_last_season_hallfame": h_hallfame,
    "/bookmark/get_bookmarks": h_get_bookmarks,
}


def parse_params(raw):
    text = raw.decode("utf-8", errors="replace")
    try:
        vals = parse_qs(text, keep_blank_values=True).get("params")
        if vals:
            return json.loads(vals[0]), text
    except ValueError:
        pass
    try:
        return json.loads(text), text
    except ValueError:
        return {}, text


class Handler(BaseHTTPRequestHandler):
    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        params, text = parse_params(raw)

        path = PADDING.sub("", self.path.split("?")[0]) or "/"

        handler = HANDLERS.get(path)
        if handler is None and path.startswith("/user_tag/add_point"):
            handler = h_add_point          # add_point_* variants
        tag = "" if handler else "  >>> UNHANDLED <<< [no special handler, sent plain success]"
        try:
            reply = (handler or (lambda p: ok()))(params)
        except Exception as e:  # never let the server crash mid-game
            reply = ok()
            tag += "  [handler error: %s]" % e
        out = json.dumps(reply).encode()

        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        shown = json.dumps(params)[:600] if params else text[:600]
        lines = [
            "[%s] %s %s%s" % (stamp, self.command, path, tag),
            "      sent: %s" % shown,
            "      reply: %s" % out.decode()[:400],
        ]
        print("\n".join(lines), flush=True)
        try:
            with open(LOGFILE, "a") as f:
                f.write("\n".join(lines) + "\n")
            with open(FULLLOG, "a") as f:
                f.write("[%s] %s %s%s\nSENT : %s\nREPLY: %s\n\n" % (
                    stamp, self.command, path, tag,
                    json.dumps(params) if params else text, out.decode()))
        except OSError:
            pass

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_PUT = do_DELETE = _handle

    def log_message(self, *args):
        pass


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "?"
    finally:
        s.close()


if __name__ == "__main__":
    print("Dear My Cat server listening on port %d" % PORT, flush=True)
    print("This computer's address: %s  (must match the address you patched in)" % local_ip())
    print("save: %s\nlog:  %s\nfull: %s" % (SAVEFILE, LOGFILE, FULLLOG), flush=True)
    print("daily limits: %s" % ("real 24h timer" if ARGS.real_daily_reset
                                else "reset on every game login"), flush=True)
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
