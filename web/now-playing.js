// Drop-in "now playing" card for your website. Setup is in the README.
//
//   <div data-now-playing></div>
//   <script src="now-playing.js" data-endpoint="https://nowplaying.YOUR-NAME.workers.dev" defer></script>
//
// Optional attributes on the <script> tag:
//   data-hide-when-idle   hide the card completely when nothing is playing
//   data-idle-text="..."  what to show when nothing is playing
//   data-country="gb"     which Apple Music storefront to look up album art and links in (default "us")

(() => {
  const script = document.currentScript;
  const ENDPOINT = script.dataset.endpoint;
  const HIDE_WHEN_IDLE = script.hasAttribute("data-hide-when-idle");
  const IDLE_TEXT = script.dataset.idleText ?? "Not listening to anything right now";
  const COUNTRY = script.dataset.country ?? "us";
  const POLL_MS = 30 * 1000;

  if (!ENDPOINT) {
    console.error("now-playing.js: add data-endpoint=\"https://your-worker.workers.dev\" to the script tag");
    return;
  }

  // :where() keeps these at zero specificity so your own CSS always wins
  const style = document.createElement("style");
  style.textContent = `
    :where(.np) {
      --np-bg: #ffffff; --np-fg: #1d1d1f; --np-muted: #6e6e73; --np-accent: #fa2d48; --np-border: #e5e5ea;
      display: flex; align-items: center; gap: 12px; max-width: 360px; padding: 10px 14px 10px 10px;
      border: 1px solid var(--np-border); border-radius: 14px; background: var(--np-bg); color: var(--np-fg);
      font: 14px/1.35 system-ui, -apple-system, "Segoe UI", sans-serif; text-decoration: none;
    }
    @media (prefers-color-scheme: dark) {
      :where(.np) { --np-bg: #1c1c1e; --np-fg: #f5f5f7; --np-muted: #a1a1a6; --np-border: #2c2c2e; }
    }
    :where(.np[hidden]) { display: none; }
    :where(.np-art) {
      flex: none; width: 56px; height: 56px; border-radius: 8px; object-fit: cover;
      background: var(--np-border);
    }
    :where(.np-art[src=""]) { visibility: hidden; }
    :where(.np-text) { display: flex; flex-direction: column; min-width: 0; }
    :where(.np-label) {
      display: flex; align-items: center; gap: 6px; color: var(--np-accent);
      font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
    }
    :where(.np-title, .np-artist) { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
    :where(.np-title) { font-weight: 600; }
    :where(.np-artist) { color: var(--np-muted); }
    :where(.np-bars) { display: inline-flex; align-items: flex-end; gap: 2px; height: 10px; }
    :where(.np-bars i) { width: 2px; height: 100%; background: currentColor; animation: np-bounce 1s ease-in-out infinite; }
    :where(.np-bars i:nth-child(2)) { animation-delay: -.4s; }
    :where(.np-bars i:nth-child(3)) { animation-delay: -.7s; }
    :where(.np.is-idle .np-bars, .np.is-idle .np-art) { display: none; }
    :where(.np.is-idle .np-label) { color: var(--np-muted); }
    @keyframes np-bounce { 0%, 100% { transform: scaleY(.3); } 50% { transform: scaleY(1); } }
    @media (prefers-reduced-motion: reduce) { :where(.np-bars i) { animation: none; } }
  `;
  document.head.append(style);

  const cards = [...document.querySelectorAll("[data-now-playing]")].map((root) => {
    root.innerHTML = `
      <a class="np is-idle" target="_blank" rel="noopener">
        <img class="np-art" src="" alt="">
        <span class="np-text">
          <span class="np-label"><span class="np-bars"><i></i><i></i><i></i></span><span class="np-status"></span></span>
          <span class="np-title"></span>
          <span class="np-artist"></span>
        </span>
      </a>`;
    const el = (cls) => root.querySelector(cls);
    return { card: el(".np"), art: el(".np-art"), status: el(".np-status"), title: el(".np-title"), artist: el(".np-artist") };
  });
  if (!cards.length) return;

  // the worker only knows title/artist/album, so album art and a link come from Apple's public search API
  const artwork = new Map();
  async function lookup(song) {
    const key = `${song.title}\n${song.artist}`;
    if (!artwork.has(key)) {
      const url = `https://itunes.apple.com/search?entity=song&limit=1&country=${encodeURIComponent(COUNTRY)}`
        + `&term=${encodeURIComponent(`${song.title} ${song.artist}`)}`;
      artwork.set(key, fetch(url).then((r) => r.json()).then(({ results: [hit] }) => hit && {
        art: hit.artworkUrl100.replace("100x100", "200x200"),
        link: hit.trackViewUrl,
      }).catch(() => null));
    }
    return artwork.get(key);
  }

  let current = null; // "" means idle, so start with something that can't match
  async function render(song) {
    const key = song.playing ? `${song.title}\n${song.artist}` : "";
    if (key === current) return;
    current = key;
    const found = song.playing ? await lookup(song) : null;
    if (key !== current) return; // a newer song arrived while the artwork was loading
    for (const c of cards) {
      c.card.classList.toggle("is-idle", !song.playing);
      c.card.hidden = HIDE_WHEN_IDLE && !song.playing;
      c.status.textContent = song.playing ? "Listening on Apple Music" : IDLE_TEXT;
      c.title.textContent = song.playing ? song.title : "";
      c.artist.textContent = song.playing ? song.artist : "";
      c.art.src = found?.art ?? "";
      c.art.alt = song.playing && song.album ? `${song.album} cover` : "";
      if (found?.link) c.card.href = found.link;
      else c.card.removeAttribute("href");
    }
  }

  async function poll() {
    if (document.hidden) return; // no point asking while nobody's looking
    try {
      const res = await fetch(ENDPOINT, { cache: "no-store" });
      if (res.ok) await render(await res.json());
    } catch {
      // offline or the worker is down; keep showing whatever we had
    }
  }

  render({ playing: false });
  poll();
  setInterval(poll, POLL_MS);
  document.addEventListener("visibilitychange", poll);
})();
