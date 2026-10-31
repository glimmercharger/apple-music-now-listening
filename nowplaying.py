"""Watch Apple Music on Windows and mirror the current song to your Slack status and your website."""

import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)

config = json.loads((Path(__file__).parent / "config.json").read_text())
SAVED = Path(__file__).parent / "saved_status.json"  # survives restarts so a crash mid-song can still restore

APPLE_MUSIC = "AppleInc.AppleMusicWin_nzyj5cx40ttqa!App"
EMOJI = config.get("slack_emoji") or ":headphones:"
POLL_SECONDS = 2
HEARTBEAT_SECONDS = 60      # resend to the worker so it knows the computer is still alive
SLACK_CHECK_SECONDS = 30     # while playing, how often to check nothing else has changed or cleared the status
SLACK_REFRESH_SECONDS = 300  # push the slack expiry forward once it's this close
SLACK_EXPIRY_SECONDS = 600   # status clears itself if the computer dies mid-song


def post_json(url, body, token):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        # cloudflare 403s python's default user agent
        headers={"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {token}",
                 "User-Agent": "apple-music-now-listening"},
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read() or b"{}")


def slack(method, body):
    res = post_json(f"https://slack.com/api/{method}", body, config["slack_token"])
    if not res.get("ok"):
        raise RuntimeError(f"slack {method}: {res.get('error')}")
    return res


def set_slack_status(song):
    current = slack("users.profile.get", {})["profile"]
    showing_music = current.get("status_emoji") == EMOJI
    # SAVED only exists while music has the status, so a different status now was set mid-song
    set_mid_song = SAVED.exists() and not showing_music and bool(current.get("status_text") or current.get("status_emoji"))
    if song:
        if set_mid_song:
            return  # wait for e.g. "in a meeting" to clear
        text = f"{song['title']} – {song['artist']}"
        if len(text) > 100:
            text = text[:99] + "…"
        if (showing_music and current.get("status_text") == text
                and (current.get("status_expiration") or 0) - time.time() > SLACK_REFRESH_SECONDS):
            return  # already showing, nothing to do
        if SAVED.exists() and not showing_music:
            print(f"{time.strftime('%H:%M:%S')} something else cleared the status, putting the music back")
        if not SAVED.exists():
            # remember what was there before the music (out of office, nothing, ...) to put back afterwards
            SAVED.write_text(json.dumps({k: current.get(k) or "" for k in ("status_text", "status_emoji")}
                                        | {"status_expiration": current.get("status_expiration") or 0}))
        profile = {"status_text": text, "status_emoji": EMOJI,
                   "status_expiration": int(time.time()) + SLACK_EXPIRY_SECONDS}
    elif SAVED.exists() and not set_mid_song:
        profile = json.loads(SAVED.read_text())
        # the old status keeps its original end time; if that's already passed, just clear it
        if 0 < profile["status_expiration"] <= time.time():
            profile = {"status_text": "", "status_emoji": "", "status_expiration": 0}
    else:
        # music's done; a status set mid-song stays as it is
        SAVED.unlink(missing_ok=True)
        return
    slack("users.profile.set", {"profile": profile})
    if not song:
        SAVED.unlink(missing_ok=True)


def update_site(song):
    post_json(config["worker_url"], song or {"playing": False}, config["worker_secret"])


async def current_song(manager):
    for session in manager.get_sessions():
        if session.source_app_user_model_id != APPLE_MUSIC:
            continue
        if session.get_playback_info().playback_status != PlaybackStatus.PLAYING:
            return None
        props = await session.try_get_media_properties_async()
        if not props.title:
            return None
        # the windows app packs "Artist — Album" into the artist field
        artist, _, album = props.artist.partition(" — ")
        return {"playing": True, "title": props.title, "artist": artist, "album": album or props.album_title}
    return None


async def main():
    use_slack, use_site = bool(config.get("slack_token")), bool(config.get("worker_url"))
    if not (use_slack or use_site):
        sys.exit("config.json needs a slack_token, a worker_url, or both - see the README")
    manager = await SessionManager.request_async()
    last = None
    slack_sent = site_sent = object()  # sync once on startup, e.g. restore a status left over from a crash
    last_slack = last_site = 0.0
    while True:
        try:
            song = await current_song(manager)
            now = time.monotonic()
            if song != last:
                print(f"{time.strftime('%H:%M:%S')} {song['title'] + ' – ' + song['artist'] if song else '(nothing playing)'}")
                last = song
            if use_slack and (song != slack_sent or song and now - last_slack > SLACK_CHECK_SECONDS):
                set_slack_status(song)
                slack_sent, last_slack = song, now
            if use_site and (song != site_sent or song and now - last_site > HEARTBEAT_SECONDS):
                update_site(song)
                site_sent, last_site = song, now
        except Exception as e:  # network blips shouldn't kill the watcher; anything unsent retries later
            print(f"{time.strftime('%H:%M:%S')} error: {e}")
            await asyncio.sleep(30)
        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    if sys.stdout is None:  # started by pythonw at login, so there's no console to print to
        sys.stdout = sys.stderr = open(Path(__file__).parent / "nowplaying.log", "a", encoding="utf-8", buffering=1)
    asyncio.run(main())
