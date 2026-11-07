"""
fakeserver.py - stand-in server for Dear My Cat 2.1.9, built from the game's own code.

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
  * udata / deco_data are the game's save files as JSON text; "{}" means "nothing
    stored on the server, keep the save on the device".

Saves the game uploads (user/update, deco_info/update_deco, daily quests...) are
kept in dmc_save.json in the data folder (default: next to this file) and handed back on the next login, so progress
survives reinstalls as long as you keep that file.
Every request is printed and appended to requests.log in the same folder.
A request marked [no special handler] got a generic reply; if the game freezes,
that is usually the place to look (see CONTRIBUTING.md).
"""
import argparse
import datetime
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
ARGS = _ap.parse_args()

PORT = ARGS.port
DATA_DIR = os.path.abspath(os.path.expanduser(ARGS.data_dir))
os.makedirs(DATA_DIR, exist_ok=True)
LOGFILE = os.path.join(DATA_DIR, "requests.log")
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
        tag = "" if handler else "  [no special handler, sent plain success]"
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
    print("save: %s\nlog:  %s" % (SAVEFILE, LOGFILE), flush=True)
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
