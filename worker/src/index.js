import { DurableObject } from "cloudflare:workers";

// if the computer stops checking in (closed lid, crash), stop claiming a song is playing
const STALE_MS = 3 * 60 * 1000;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
};

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });

// a durable object (rather than KV) so every visitor sees a song change immediately
export class NowPlaying extends DurableObject {
  async get() {
    const song = (await this.ctx.storage.get("song")) ?? { playing: false };
    if (song.playing && Date.now() - song.updated > STALE_MS) song.playing = false;
    return song;
  }

  async set(song) {
    await this.ctx.storage.put("song", song);
  }
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });

    const store = env.NOW_PLAYING.get(env.NOW_PLAYING.idFromName("default"));

    if (request.method === "GET") return json(await store.get());

    if (request.method === "POST") {
      if (request.headers.get("Authorization") !== `Bearer ${env.SECRET}`) return json({ error: "unauthorized" }, 401);
      const body = await request.json();
      const clean = (s) => String(s ?? "").slice(0, 200);
      await store.set({
        playing: Boolean(body.playing),
        title: clean(body.title),
        artist: clean(body.artist),
        album: clean(body.album),
        updated: Date.now(),
      });
      return json({ ok: true });
    }

    return json({ error: "method not allowed" }, 405);
  },
};
