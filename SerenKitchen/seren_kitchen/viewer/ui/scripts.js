// ── SerenKitchen: the wall, an open fridge, what is waiting, the leftovers ────
// Every sheet is drawn as a CARD (a title, a line of its note, how much is on it,
// its first picture); clicking a card opens the SHEET: everything on it, full size,
// with the lines to tick, the choices to pick, and the notes stuck on it, each one
// drawn under the line it answers. The wall and the open fridge are watched every 10 s
// through the shell's watch(): repainted only when the answer changed, quiet while hidden.
const $ = id => document.getElementById(id);
const INK_DARK = "#1b1b1f", INK_LIGHT = "#fffaf0";
let KITCHEN = null, OPEN = null, CHEESE = 0, REPLY_TO = null, SHOWN = null, GALLERY = null;
const PINS = ["#d0393e", "#2f6fb3", "#F5D76E", "#8fbf88", "#9d7cff"];
// the letters on the freezer: the six colours of a bag of fridge magnets
const MAGNET = ["#e4bd36", "#732f62", "#df3822", "#34914d", "#418dd0", "#f26407"];
const BUILD = { ok: "#34914d", failed: "#df3822", running: "#e4bd36", none: "#888888" };
const KIND_WORD = { now: "honey-do now", list: "a list", person: "to the person", other: "to the partner", self: "to self", art: "art", decision: "a decision" };
let HOUSE = { person: "", partner: "" }, HANDS = [];

// whose house: the yaml names the person and the partner, and the page says so wherever a kind is named
function nameTheHouse(k) {
  HOUSE = k.house || HOUSE;
  KIND_WORD.person = HOUSE.person ? `to ${HOUSE.person}` : "to the person";
  KIND_WORD.other = HOUSE.partner ? `to ${HOUSE.partner}` : "to the partner";
  $("optPerson").textContent = `${KIND_WORD.person} (door)`; $("optOther").textContent = `${KIND_WORD.other} (door)`;
  if (!localStorage.getItem("kitchen.me")) whoAmI(false);   // the signer defaults to the person of the house once we know who that is
  // one hand per author: a @font-face for each, and a rule that puts it on their notes
  if (JSON.stringify(k.hands || []) !== JSON.stringify(HANDS)) {
    HANDS = k.hands || [];
    let css = "";
    for (const a of HANDS) {
      const fam = "Hand-" + a.replace(/[^a-z0-9]/gi, "_");
      css += `@font-face{font-family:"${fam}";src:url(/api/fonts/hand/${encodeURIComponent(a)});font-display:swap}\n` +
        `.note[data-author="${a}"] h4,.note[data-author="${a}"] p,.note[data-author="${a}"] li,.note[data-author="${a}"] .by,.note[data-author="${a}"] .who{font-family:"${fam}",var(--f-hand)}\n`;
    }
    let st = $("handsCss"); if (!st) { st = document.createElement("style"); st.id = "handsCss"; document.head.append(st); }
    st.textContent = css;
  }
}
// who left it, with the hand when the author has more than one on the board
function byLine(s) { return (s.author || "someone") + (s.hand ? " · " + s.hand : ""); }
function authorAttr(s) { return `data-author="${escapeHtml((s.author || "").trim().toLowerCase())}"`; }

function say(id, text, bad) { const m = $(id); if (!m) return; m.textContent = text || ""; m.className = "msg" + (text ? (bad ? " bad" : " ok") : ""); }
function why(e) { return /^401/.test(e.message) ? "The kitchen wants its token (🔑 Token, top right)." : e.message; }
async function detail(e, path) {
  // the API's reason in plain words, when it gave one
  try { const r = await fetch(path); if (!r.ok) { const j = await r.json(); if (j.detail) return j.detail; } } catch (_) { /* the message stands */ }
  return why(e);
}

// ── colour sums, so ink and shade follow each fridge's own colour ─────────────
function rgb(h) { h = h.replace("#", ""); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); }
function lum(h) { const f = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }; const [r, g, b] = rgb(h); return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); }
function contrast(a, b) { const la = lum(a), lb = lum(b); return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05); }
function shade(h, k) { const t = k < 0 ? 0 : 255; k = Math.abs(k); return "#" + rgb(h).map(c => Math.round(c + (t - c) * k).toString(16).padStart(2, "0")).join(""); }
function inkFor(accent) { return contrast(accent, INK_DARK) >= contrast(accent, INK_LIGHT) ? INK_DARK : INK_LIGHT; }
function namePx(display, base) { const n = display.length; return n <= 8 ? base : n <= 11 ? Math.round(base * 0.8) : Math.round(base * 0.62); }
function fridgeVars(f, base) {
  return `--accent:${f.accent};--freezer:${shade(f.accent, -0.18)};--edge:${shade(f.accent, -0.35)};--fink:${inkFor(f.accent)};--name-px:${namePx(f.display, base)}px`;
}

// ── the freezer's letters: each one a different magnet, like the bag they came in ──
function letters(text, seed) {
  let i = seed || 0;
  return Array.from(String(text)).map(ch => ch === " " ? " " : `<span style="color:${MAGNET[(i++) % MAGNET.length]}">${escapeHtml(ch)}</span>`).join("");
}
function freezerHtml(f, big) {
  const facts = f.facts || {};
  const rel = facts.release ? letters("RELEASE: " + facts.release, f.display.length) : `<span class="dim">RELEASE: ${letters("—", 2)}</span>`;
  const b = facts.build || "none";
  const word = { ok: "BUILD OK", failed: "BUILD FAILED", running: "BUILDING", none: "NO BUILD" }[b] || b.toUpperCase();
  const dot = `<span class="dot" style="--dot:${BUILD[b] || BUILD.none}" title="${escapeHtml(b)}${facts.build_at ? " · " + facts.build_at : ""}"></span>`;
  const link = facts.build_url && big ? ` <a class="tiny" href="${escapeHtml(facts.build_url)}" target="_blank" rel="noopener" style="color:var(--fink);opacity:.7">run ↗</a>` : "";
  const err = facts.freezer_error ? `<div class="facts-err" title="${escapeHtml(facts.freezer_error)}">github unreadable</div>` : "";
  // the dispenser: an ice-maker button that polls this one fridge's runs
  const dispenser = big ? `<button class="dispenser" id="dispenser" title="poll this fridge's release and build now"><span class="chute"></span><span class="lever">ICE · POLL</span></button>` : "";
  return `<div class="facts"><div class="rel">${rel}</div><div class="build">${dot}${letters(word, f.display.length + 3)}${link}</div>${err}</div>${dispenser}`;
}

// ── who signs ────────────────────────────────────────────────────────────────
function whoAmI(ask) {
  // no prompt on load: a dialog before the wall is painted is rude, and it stalls a headless browser cold
  const fallback = HOUSE.person || "someone";
  let me = localStorage.getItem("kitchen.me") || fallback;
  if (ask) { me = (prompt("Who signs what you leave on the fridge?", me) || me).trim().slice(0, 40) || fallback; }
  localStorage.setItem("kitchen.me", me);
  $("pillMe").textContent = "signed " + me;
  return me;
}

// ── a card: the glance at a sheet ───────────────────────────────────────────
function pinOf(s) { return s.pin || PINS[(s.id.charCodeAt(0) + s.id.charCodeAt(1)) % PINS.length]; }
function pinHtml(s, cls = "pin") {
  // a sheet about cheese is pinned with cheese. obviously.
  if (/cheese/i.test(s.title || "")) return `<div class="${cls} food" title="🧀">🧀</div>`;
  return `<div class="${cls}" style="background:${escapeHtml(pinOf(s))}"></div>`;
}
function excerpt(text, n) { text = (text || "").replace(/\s+/g, " ").trim(); return text.length > n ? text.slice(0, n - 1) + "…" : text; }
function cardHtml(s, opts = {}) {
  const open = s.open_lines, total = (s.lines || []).length, stuck = (s.replies || []).length;
  const bits = [];
  if (total) bits.push(open ? `${open} of ${total} left` : `${total} ticked`);
  if (s.waiting) bits.push("waiting on a pick");
  if (stuck) bits.push(`${stuck} stuck on`);
  if (s.art && s.art.length > 1) bits.push(`${s.art.length} pictures`);
  const pic = s.art && s.art.length ? `<img class="thumb" src="/api/art/${escapeHtml(s.art[0])}" alt="" loading="lazy">` : "";
  const note = s.body ? `<p class="ex">${escapeHtml(excerpt(s.body, opts.tiny ? 60 : 110))}</p>` : (!total && !pic ? "" : "");
  const first = !s.body && total ? `<p class="ex">${escapeHtml(excerpt(s.lines[0].text, opts.tiny ? 50 : 90))}${total > 1 ? " …" : ""}</p>` : "";
  const where = opts.where ? `<div class="where">${escapeHtml(opts.where)}</div>` : "";
  const style = opts.pos ? `--x:${s.x}px;--y:${s.y}px;--rot:${s.rot}deg` : `--rot:${s.rot}deg`;
  return `<div class="note card-note ${s.sour ? "sour" : ""} ${opts.tiny ? "tiny-card" : ""} ${s.done_at ? "finished" : ""}" style="${style}" data-open="${s.id}" ${authorAttr(s)} title="open this sheet">` +
    `${pinHtml(s)}<h4>${escapeHtml(s.title)}</h4>${pic}${note}${first}` +
    `<div class="by">${escapeHtml(byLine(s))}${bits.length ? " · " + escapeHtml(bits.join(" · ")) : ""}${s.sour ? " · gone off" : ""}</div>${where}</div>`;
}

// ── the sheet: everything on it, full size ──────────────────────────────────
function galleryHtml(s) {
  if (!s.art || !s.art.length) return "";
  const many = s.art.length > 1;
  return `<div class="gallery" data-sheet="${s.id}" data-n="${s.art.length}">` +
    s.art.map((a, i) => `<figure class="${i === 0 ? "on" : ""}" data-i="${i}"><a href="/api/art/${escapeHtml(a)}" target="_blank" rel="noopener"><img src="/api/art/${escapeHtml(a)}" alt="${escapeHtml(s.title)}"></a>` +
      `<button class="ghost drop-art" data-sheet="${s.id}" data-art="${escapeHtml(a)}" title="take this picture off">✕</button></figure>`).join("") +
    (many ? `<button class="gal-btn prev" title="previous">‹</button><button class="gal-btn next" title="next">›</button><div class="gal-dots">${s.art.map((_, i) => `<span class="${i === 0 ? "on" : ""}"></span>`).join("")}</div>` : "") +
    `</div>`;
}

function lineHtml(s, ln, i, acts) {
  const picked = ln.pick ? `<span class="picked">→ ${escapeHtml(ln.pick)}</span>` : "";
  const choices = ln.options && !ln.pick && acts ? `<div class="acts choices">${ln.options.map(o => `<button data-pick-line="${i}" data-sheet="${s.id}" data-option="${escapeHtml(o)}">${escapeHtml(o)}</button>`).join("")}</div>`
    : (ln.options && !ln.pick ? `<span class="tiny dim"> (${ln.options.length} choices)</span>` : "");
  const answers = (s.replies || []).filter(r => r.reply_line === i);
  const tick = ln.options ? "" : `<input type="checkbox" data-sheet="${s.id}" data-line="${i}" ${ln.done ? "checked" : ""} ${acts ? "" : "disabled"}>`;
  return `<li class="${ln.done ? "done" : ""} ${ln.options ? "choice" : ""}"><label>${tick} ${escapeHtml(ln.text)}</label>${picked}` +
    (acts ? `<button class="ghost" data-reply="${s.id}" data-line="${i}" title="stick a note on this line">↩</button>` : "") + choices +
    (answers.length ? `<div class="answers">${answers.map(r => replyHtml(r, acts)).join("")}</div>` : "") + `</li>`;
}

function replyHtml(r, acts) {
  // a note stuck on a note: smaller, its own paper, who and when up top so a 9am reader knows what it is
  return `<div class="note reply" style="--rot:${r.rot}deg" data-id="${r.id}" ${authorAttr(r)}>${pinHtml(r, "pin small")}` +
    `<div class="who">${escapeHtml(byLine(r))} stuck this on · ${escapeHtml((r.made || "").slice(0, 10))}</div><h4>${escapeHtml(r.title)}</h4>` +
    galleryHtml(r) + (r.body ? `<p class="body">${escapeHtml(r.body)}</p>` : "") +
    ((r.lines || []).length ? `<ul>${r.lines.map((ln, i) => lineHtml(r, ln, i, acts)).join("")}</ul>` : "") +
    (acts ? `<div class="acts"><button data-reply="${r.id}">stick a note on</button><button data-down="${r.id}" title="off for good">✕</button></div>` : "") + `</div>`;
}

function sheetHtml(s, opts = {}) {
  const acts = opts.acts !== false;
  const lines = (s.lines || []).length ? `<ul>${s.lines.map((ln, i) => lineHtml(s, ln, i, acts)).join("")}</ul>` : "";
  const legacy = s.kind === "decision" && s.options && !s.pick && acts ? `<div class="acts choices">${s.options.map(o => `<button data-pick="${escapeHtml(o)}" data-sheet="${s.id}">${escapeHtml(o)}</button>`).join("")}</div>` : "";
  const picked = s.pick ? `<p><b>picked:</b> ${escapeHtml(s.pick)}</p>` : "";
  const finish = s.done_at ? `<button data-undone="${s.id}">back where it was</button>` : `<button data-done="${s.id}">done</button>`;
  const sheetReplies = (s.replies || []).filter(r => r.reply_line == null);
  const where = `${escapeHtml(KIND_WORD[s.kind] || s.kind)} on the ${escapeHtml(s.place)} of ${escapeHtml(display(s.fridge))}`;
  return `<div class="note full ${s.sour ? "sour" : ""}" style="--rot:${s.rot}deg" data-id="${s.id}" ${authorAttr(s)}>` +
    `${pinHtml(s)}<div class="paper">` +
    `<div class="who">${escapeHtml(byLine(s))} · ${escapeHtml((s.made || "").slice(0, 10))} · ${where}${s.sour ? " · gone off" : ""}${s.ref ? ` · ${escapeHtml(s.ref)}` : ""}</div>` +
    `<h4>${escapeHtml(s.title)}</h4>` + galleryHtml(s) + (s.body ? `<p class="body">${escapeHtml(s.body)}</p>` : "") + lines + picked + legacy +
    (acts ? `<div class="acts main">${finish}<button data-reply="${s.id}">stick a note on</button><button data-add-art="${s.id}">add a picture</button><button data-down="${s.id}" title="off the fridge for good">✕</button></div>` : "") +
    (sheetReplies.length ? `<div class="replies"><div class="tiny dim">stuck on this sheet</div>${sheetReplies.map(r => replyHtml(r, acts)).join("")}</div>` : "") + `</div></div>`;
}

function magnetHtml(m, extraClass = "") {
  const face = m.picture ? `<img src="${m.picture}" alt="${escapeHtml(m.partner)}">` : `<div class="blank">${escapeHtml(m.partner.slice(0, 2))}</div>`;
  const who = m.label || m.partner;
  const tag = m.hand ? `<span class="tag">${escapeHtml(m.hand)}</span>` : "";
  // a magnet with a session wears its state: live, idle, ended (its session ended), missing (gone past the milk days)
  const state = m.state ? ` ${m.state}` : "";
  const tip = `${who} holds this${m.since ? " since " + m.since.slice(0, 16) : ""}` + (m.state ? ` · ${m.state}` : "") +
    (m.session ? ` · session ${m.session}` : "") + (m.end_reason ? ` (${m.end_reason})` : "") + ". Click: copy how to start their session.";
  return `<div class="magnet ${extraClass}${state}" style="left:${m.x}px;top:${m.y}px" title="${escapeHtml(tip)}" data-partner="${escapeHtml(who)}">${face}${tag}</div>`;
}

// ── the wall ─────────────────────────────────────────────────────────────────
// ── the big fridge: the little fridges are polaroids on its door, the house's own sheets beside them ──
let DRAG = null;
function polaroidHtml(f, k, i) {
  const held = k.magnets.filter(m => m.fridge === f.name);
  const notes = k.doors.filter(s => s.fridge === f.name);
  const facts = f.facts || {}; const b = facts.build || "none";
  const inside = f.counts.shelf + f.counts.crisper;
  const bare = !held.length && !notes.length;
  return `<figure class="polaroid" style="--rot:${(-5 + (i * 7) % 11)}deg" data-fridge="${f.name}" draggable="false">` +
    `<span class="tape" draggable="true" title="drag to move this fridge"></span>` +
    `<div class="mini" style="${fridgeVars(f, 14)}">` +
      `<div class="mfreezer"><div class="mname">${escapeHtml(f.display)}</div><div class="mfacts">${letters("v" + (facts.release || "—"), f.display.length)} <span class="dot" style="--dot:${BUILD[b] || BUILD.none}"></span></div><span class="mhandle top"></span></div>` +
      `<div class="mdoor ${bare ? "bare" : ""}"><span class="mhandle"></span>${held.map(m => `<img class="mmagnet" src="${m.picture || ""}" alt="${escapeHtml(m.partner)}" title="${escapeHtml(m.partner)} holds this">`).join("")}` +
        notes.slice(0, 3).map((s, j) => `<div class="mnote" style="--r:${(j * 9) % 13 - 6}deg" title="${escapeHtml(s.title)}"></div>`).join("") + `</div>` +
    `</div>` +
    `<figcaption>${escapeHtml(f.display)}<span class="cnt">${f.counts.door} on the door · ${inside} inside · ${f.counts.leftovers} done${f.sour ? " · sour" : ""}</span></figcaption></figure>`;
}

function paintWall() {
  const k = KITCHEN; if (!k) return;
  $("pillDoors").textContent = `${k.doors.length} on the doors`;
  const sour = k.fridges.reduce((n, f) => n + f.sour, 0);
  $("pillSour").hidden = !sour; $("pillSour").textContent = `${sour} gone sour`; $("pillSour").style.color = "var(--danger)";
  const house = (k.house && k.house.fridge) || "seren-project";
  document.body.classList.toggle("hinge-left", (k.house && k.house.hinge) === "left");
  const little = k.fridges.filter(f => f.name !== house);
  $("bigSub").innerHTML = letters(`ONE BIG FRIDGE · ${little.length} LITTLE ONES`, 2);
  // the freezer: the house's own door notes, as cards; the big door: the house's lists and art
  const hf = k.fridges.find(f => f.name === house);
  const fz = k.doors.filter(s => s.fridge === house).slice(0, 4);
  $("fzNotes").innerHTML = fz.map((s, i) => cardHtml({ ...s, rot: (-3 + (i * 7) % 7) }, {})).join("") + (fz.length ? "" : `<div class="fzempty">${letters("NOTHING ON THE FREEZER", 1)}</div>`);
  $("houseNotes").innerHTML = (hf && (hf.counts.shelf + hf.counts.crisper) ? `<button class="small house-open" data-open-house="${house}">the house's lists and art: ${hf.counts.shelf + hf.counts.crisper} inside, ${hf.counts.leftovers} done →</button>` : "");
  $("houseNotes").hidden = !$("houseNotes").innerHTML;
  const bigdoor = $("houseNotes").parentElement;
  if ((k.house && k.house.notes_at) === "bottom") bigdoor.append($("houseNotes")); else bigdoor.insertBefore($("houseNotes"), $("room"));
  $("room").innerHTML = little.map((f, i) => polaroidHtml(f, k, i)).join("");
  $("room").querySelectorAll(".polaroid").forEach(el => {
    el.onclick = e => { if (e.target.closest(".tape")) return; openFridge(el.dataset.fridge); };
    const tape = el.querySelector(".tape");
    tape.ondragstart = e => { DRAG = el.dataset.fridge; el.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; try { e.dataTransfer.setData("text/plain", DRAG); } catch (_) { /* some browsers */ } };
    tape.ondragend = () => { el.classList.remove("dragging"); DRAG = null; $("room").querySelectorAll(".over").forEach(x => x.classList.remove("over")); };
    el.ondragover = e => { if (!DRAG || DRAG === el.dataset.fridge) return; e.preventDefault(); el.classList.add("over"); };
    el.ondragleave = () => el.classList.remove("over");
    el.ondrop = async e => {
      e.preventDefault(); el.classList.remove("over");
      if (!DRAG || DRAG === el.dataset.fridge) return;
      const order = [...$("room").querySelectorAll(".polaroid")].map(p => p.dataset.fridge);
      const from = order.indexOf(DRAG), to = order.indexOf(el.dataset.fridge);
      order.splice(from, 1); order.splice(to, 0, DRAG);
      try { await api("/api/settings/order", { method: "POST", body: JSON.stringify({ order: [house].concat(order) }) }); await loadWall(); toast("moved."); }
      catch (err) { toast(why(err)); }
    };
  });
  $("fzNotes").querySelectorAll("[data-open]").forEach(el => el.onclick = e => { e.stopPropagation(); openFridge(house, true).then(() => openSheet(el.dataset.open)); });
  $("houseNotes").querySelectorAll("[data-open-house]").forEach(b => b.onclick = () => openFridge(house));
  const loose = k.magnets.filter(m => !m.fridge);
  $("counterMagnets").innerHTML = loose.length ? loose.map(m => magnetHtml(m, "counter")).join("") : `<span class="tiny" style="color:#eee8d8;opacity:.7;font-family:var(--f-hand)">no loose magnets on the counter</span>`;
  $("counterMagnets").querySelectorAll(".magnet").forEach(el => el.onclick = () => copyStarter(el.dataset.partner));
}

// ── the polling pair, from the Meninges shell (>= 6.2.0) ─────────────────────
// watch() asks every ten seconds and calls paint only when the answer changed, so nothing under a reader's
// eye (or an inspector's cursor) is replaced for no reason; nothing is asked while the tab is hidden, and one
// round runs the moment it is shown. The same mechanism every viewer in the family uses, not a copy of it.
let WALL = null, FRIDGE_W = null, FRIDGE_BAD = false;
function startWatching() {
  WALL = watch("/api/kitchen", 10000, k => { KITCHEN = k; nameTheHouse(k); paintWall(); repaintShown(); },
    { whileVisible: true, onError: e => { $("room").innerHTML = `<p class="muted">${escapeHtml(why(e))}</p>`; } });
  // the open fridge is a question that moves: a falsy path sits the round out while no fridge is open, and the
  // path is part of the answer's signature, so a different fridge with the same JSON still repaints
  FRIDGE_W = watch(() => OPEN && `/api/fridges/${encodeURIComponent(OPEN)}`, 10000, f => { FRIDGE_BAD = false; paintFridge(f); },
    { whileVisible: true, onError: e => { FRIDGE_BAD = true; toast(why(e)); } });
}
// after a POST: ask again now, the wall and the open fridge, and resolve once answers asked after the POST are in
async function loadWall() {
  if (!WALL) return;
  await WALL.check();
  if (OPEN) await FRIDGE_W.check();
}

function copyStarter(partner) {
  const m = (KITCHEN.magnets || []).find(m => (m.label || m.partner) === partner);
  if (!m) return;
  const text = m.starter || `(no session starter on ${partner}'s magnet yet)`;
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(
    () => toast(`${partner}'s session starter copied.`), () => prompt(`${partner}'s session starter:`, text));
}

function toast(text) {
  let t = $("kitchenToast");
  if (!t) { t = document.createElement("div"); t.id = "kitchenToast"; t.style.cssText = "position:fixed;left:50%;bottom:28px;transform:translateX(-50%);background:#1b1b1f;color:#fff8e1;padding:8px 14px;border-radius:8px;font-family:var(--f-hand);font-size:16px;z-index:60;box-shadow:0 4px 12px rgba(0,0,0,.4);transition:opacity .3s"; document.body.append(t); }
  t.textContent = text; t.style.opacity = 1; clearTimeout(t._h); t._h = setTimeout(() => { t.style.opacity = 0; }, 2600);
}

// ── an open fridge ───────────────────────────────────────────────────────────
let FRIDGE = null, SHOWN_SIG = "";
// open a fridge: it is the watch's question from here on, and its first answer is waited for. `quiet` is a
// refresh behind the scenes (a sheet opened off the freezer, a fridge named in the hash): no tab switch.
async function openFridge(name, quiet) {
  OPEN = name;
  await FRIDGE_W.check();
  if (!quiet && !FRIDGE_BAD) showTab("fridge");
}

// the fridge's paint: watch() calls it only when the fridge's answer changed, so a reader is not shoved back
// to the top of whatever they were reading every ten seconds
function paintFridge(f) {
  FRIDGE = f;
  $("fridgeEmpty").hidden = true; $("open").hidden = false;
  const root = $("open");
  root.style.cssText = fridgeVars(f, 30);
  $("oName").textContent = f.display;
  $("oFacts").innerHTML = freezerHtml(f, true);
  $("dispenser").onclick = dispense;
  $("oDoor").innerHTML = `<div class="handle"></div><div class="magnets">${f.magnets.map(m => magnetHtml(m)).join("")}</div>` +
    f.door.map((s, i) => cardHtml({ ...s, x: 8 + (i % 3) * 14 }, { tiny: false })).join("") +
    (f.door.length ? "" : `<div class="empty">the door is bare.</div>`);
  $("oHeld").textContent = f.magnets.length ? `held by ${f.magnets.map(m => (m.label || m.partner) + (m.state && m.state !== "live" ? ` (${m.state})` : "")).join(", ")}` : "nobody is holding this one";
  const all = f.door.concat(f.shelf, f.crisper);
  $("oDoorList").innerHTML = f.door.map(s => cardHtml(s)).join("") || `<span class="tiny muted">the door is bare</span>`;
  $("oShelf").innerHTML = f.shelf.map(s => cardHtml(s)).join("") || `<span class="tiny muted">no lists</span>`;
  const waiting = all.filter(s => s.waiting);
  $("oDecisions").innerHTML = waiting.map(s => sheetHtml(s)).join("") || `<span class="tiny muted">nothing waiting</span>`;
  $("oCrisper").innerHTML = f.crisper.map(s => cardHtml(s)).join("") || `<span class="tiny muted">no art yet</span>`;
  // the leftovers are a drawer at the bottom: closed until pulled, since that is all that is done and it only grows
  $("oDrawerCount").textContent = f.leftovers.length ? `${f.leftovers.length} done` : "empty";
  $("oLeftovers").innerHTML = (f.leftovers.slice(0, 24).map(s => cardHtml(s)).join("") || `<span class="tiny muted">nothing finished yet</span>`) +
    (f.leftovers.length > 24 ? `<p class="tiny muted" style="width:100%">and ${f.leftovers.length - 24} more; the Leftovers tab has every one.</p>` : "");
  const pulled = localStorage.getItem("kitchen.drawer") === "open";
  $("oDrawerInside").hidden = !pulled; $("oDrawer").classList.toggle("open", pulled);
  $("oLeave").textContent = `Leave a note on ${f.display}`;
  wire(root);
  root.querySelectorAll(".magnet").forEach(el => el.onclick = () => copyStarter(el.dataset.partner));
  repaintShown();
}

// the open sheet follows the board (a reply lands under it while it is read), but only when it changed,
// and the paper stays where it was scrolled to
function repaintShown() {
  if (SHOWN && !$("sheetDlg").open) SHOWN = null;
  if (!SHOWN) return;
  const s = findSheet(SHOWN);
  if (!s) return;
  // this signature is of data the page already holds, not of a url, so the comparison stays here; the scroll
  // half is the shell's: the selector, since paintSheet replaces the paper and the new one is found afterwards
  if (JSON.stringify(s) === SHOWN_SIG) return;
  keepingScroll("#sheetFull .paper", () => paintSheet(s));
}

function findSheet(id) {
  const pools = [].concat(FRIDGE ? FRIDGE.door.concat(FRIDGE.shelf, FRIDGE.crisper, FRIDGE.leftovers) : [], KITCHEN ? KITCHEN.doors : []);
  for (const s of pools) { if (s.id === id) return s; for (const r of s.replies || []) if (r.id === id) return r; }
  return null;
}

async function dispense() {
  const b = $("dispenser"); b.classList.add("pressed");
  try {
    await api(`/api/fridges/${encodeURIComponent(OPEN)}/freezer`, { method: "POST" });
    toast("clunk. ice. the freezer read GitHub.");
    await loadWall();
  } catch (e) { toast(await detail(e, `/api/fridges/${encodeURIComponent(OPEN)}`)); }
  setTimeout(() => b.classList.remove("pressed"), 600);
}

// ── the sheet modal ──────────────────────────────────────────────────────────
async function openSheet(id) {
  let s = findSheet(id);
  if (!s) { try { s = await api(`/api/sheets/${id}`); } catch (e) { toast(why(e)); return; } }
  SHOWN = id;
  paintSheet(s);
  if (!$("sheetDlg").open) $("sheetDlg").showModal();
}

function paintSheet(s) {
  SHOWN_SIG = JSON.stringify(s);
  const box = $("sheetFull");
  box.innerHTML = `<div class="sheet-top"><span class="tiny">${escapeHtml(display(s.fridge))} · ${escapeHtml(s.place)}</span></div>` + sheetHtml(s);
  wire(box);
  wireGalleries(box);
}

// ── tidy: every note straight, no turning galleries (for whoever needs it; the default follows the OS's reduced-motion) ──
function tidyOn() {
  const stored = localStorage.getItem("kitchen.tidy");
  if (stored != null) return stored === "on";
  return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
function applyTidy() {
  const on = tidyOn();
  document.body.classList.toggle("tidy", on);
  $("pillTidy").textContent = on ? "tidy: on" : "tidy: off";
}
function toggleTidy() {
  try { localStorage.setItem("kitchen.tidy", tidyOn() ? "off" : "on"); } catch (_) { /* a private window */ }
  applyTidy();
}

function wireGalleries(root) {
  root.querySelectorAll(".gallery").forEach(g => {
    const figs = [...g.querySelectorAll("figure")], dots = [...g.querySelectorAll(".gal-dots span")];
    let i = 0;
    const show = n => { i = (n + figs.length) % figs.length; figs.forEach((f, k) => f.classList.toggle("on", k === i)); dots.forEach((d, k) => d.classList.toggle("on", k === i)); };
    const prev = g.querySelector(".prev"), next = g.querySelector(".next");
    if (prev) prev.onclick = e => { e.preventDefault(); show(i - 1); rest(); };
    if (next) next.onclick = e => { e.preventDefault(); show(i + 1); rest(); };
    let timer = figs.length > 1 && !tidyOn() ? setInterval(() => show(i + 1), 5000) : null;   // the little rotating gallery, still when tidy
    function rest() { if (timer) { clearInterval(timer); timer = setInterval(() => show(i + 1), 7000); } }
    g.querySelectorAll(".drop-art").forEach(b => b.onclick = async e => {
      e.preventDefault(); e.stopPropagation();
      if (!confirm("Take this picture off the sheet?")) return;
      try { await api(`/api/sheets/${b.dataset.sheet}/art/${b.dataset.art}`, { method: "DELETE" }); await refresh(); } catch (err) { toast(why(err)); }
    });
  });
}

function wire(root) {
  root.querySelectorAll("[data-open]").forEach(el => el.onclick = e => { e.stopPropagation(); openSheet(el.dataset.open); });
  root.querySelectorAll("input[type=checkbox][data-sheet]").forEach(cb => cb.onchange = () => patchSheet(cb.dataset.sheet, { [cb.checked ? "tick" : "untick"]: [Number(cb.dataset.line)] }));
  root.querySelectorAll("button[data-done]").forEach(b => b.onclick = () => patchSheet(b.dataset.done, { done: true }));
  root.querySelectorAll("button[data-undone]").forEach(b => b.onclick = () => patchSheet(b.dataset.undone, { done: false }));
  root.querySelectorAll("button[data-pick]").forEach(b => b.onclick = () => patchSheet(b.dataset.sheet, { pick: b.dataset.pick }));
  root.querySelectorAll("button[data-pick-line]").forEach(b => b.onclick = () => patchSheet(b.dataset.sheet, { pick_line: { line: Number(b.dataset.pickLine), option: b.dataset.option } }));
  root.querySelectorAll("button[data-reply]").forEach(b => b.onclick = () => openLeave({ replyTo: b.dataset.reply, line: b.dataset.line != null ? Number(b.dataset.line) : null }));
  root.querySelectorAll("button[data-add-art]").forEach(b => b.onclick = () => addArt(b.dataset.addArt));
  root.querySelectorAll("button[data-down]").forEach(b => b.onclick = async () => {
    if (!confirm("Off the fridge for good? Finished sheets keep themselves in the leftovers; this one is gone, and anything stuck to it with it.")) return;
    try { await api(`/api/sheets/${b.dataset.down}`, { method: "DELETE" }); if (SHOWN === b.dataset.down) { $("sheetDlg").close(); SHOWN = null; } await refresh(); } catch (e) { toast(why(e)); }
  });
}

async function patchSheet(id, change) {
  try { await api(`/api/sheets/${id}`, { method: "PATCH", body: JSON.stringify(change) }); await refresh(); }
  catch (e) { toast(await detail(e, `/api/sheets/${id}`)); }
}

async function refresh() { await loadWall(); await loadLists(); }

async function uploadArt(id, files) {
  for (const file of files) {
    const headers = { "Content-Type": file.type || "application/octet-stream" }, tok = getToken();
    if (tok) headers.Authorization = "Bearer " + tok;
    const r = await fetch(`/api/sheets/${id}/art`, { method: "POST", headers, body: file });
    if (!r.ok) { let d = `${r.status}`; try { d = (await r.json()).detail || d; } catch (_) { /* not JSON */ } toast(`${file.name}: ${d}`); }
  }
}

function addArt(id) {
  const input = document.createElement("input"); input.type = "file"; input.accept = "image/png,image/jpeg,image/gif,image/webp"; input.multiple = true;
  input.onchange = async () => { await uploadArt(id, [...input.files]); await refresh(); toast("on the sheet."); };
  input.click();
}

// ── leaving a sheet: a modal, with the sheet it answers shown above the form ─
async function openLeave(opts = {}) {
  REPLY_TO = opts.replyTo ? { id: opts.replyTo, line: opts.line } : null;
  const dlg = $("leaveDlg");
  $("lvParent").innerHTML = "";
  if (REPLY_TO) {
    let parent = findSheet(REPLY_TO.id);
    if (!parent) { try { parent = await api(`/api/sheets/${REPLY_TO.id}`); } catch (e) { parent = null; } }
    if (parent) {
      const line = REPLY_TO.line != null && parent.lines && parent.lines[REPLY_TO.line] ? parent.lines[REPLY_TO.line].text : null;
      $("lvParent").innerHTML = `<div class="tiny muted" style="margin-bottom:6px">sticking a note on <b>${escapeHtml(parent.title)}</b>${line != null ? `, answering the line: <i>${escapeHtml(excerpt(line, 120))}</i>` : ""}</div>` + cardHtml(parent, {});
      $("lvParent").querySelector("[data-open]").onclick = null;
    }
    $("lvKind").value = "other";
  } else if (!OPEN) { toast("Open a fridge first."); return; }
  $("lvTitle").value = ""; $("lvBody").value = ""; $("lvLines").value = ""; $("lvArt").value = "";
  $("lvHead").textContent = REPLY_TO ? "Stick a note on" : `Leave a note on ${display(OPEN)}`;
  say("lvMsg", "");
  if ($("sheetDlg").open) $("sheetDlg").close();
  dlg.showModal();
  $("lvTitle").focus();
}

async function leaveSheet() {
  const kind = $("lvKind").value;
  const body = { kind, title: $("lvTitle").value, body: $("lvBody").value, lines: $("lvLines").value.split("\n").map(s => s.trim()).filter(Boolean), author: whoAmI(false) };
  if (!body.title.trim() && !body.body.trim() && !body.lines.length) { say("lvMsg", "Give it something to read: a title, a note or a line.", true); return; }
  try {
    let made;
    if (REPLY_TO) { if (REPLY_TO.line != null) body.line = REPLY_TO.line; made = await api(`/api/sheets/${REPLY_TO.id}/reply`, { method: "POST", body: JSON.stringify(body) }); }
    else made = await api(`/api/fridges/${encodeURIComponent(OPEN)}/sheets`, { method: "POST", body: JSON.stringify(body) });
    await uploadArt(made.id, [...$("lvArt").files]);
    $("leaveDlg").close(); toast(lateHour() ? "on the fridge. it's late; the fridge will keep. go to bed." : REPLY_TO ? "Stuck on." : "On the fridge.");
    await refresh();
    if (REPLY_TO) openSheet(REPLY_TO.id);
  } catch (e) {
    say("lvMsg", await detail(e, REPLY_TO ? `/api/sheets/${REPLY_TO.id}` : `/api/fridges/${encodeURIComponent(OPEN)}`), true);
  }
}

// ── the lists ────────────────────────────────────────────────────────────────
async function loadLists() {
  try {
    const open = await api("/api/sheets?waiting=true");
    open.sort((a, b) => (a.made || "").localeCompare(b.made || ""));
    $("pillWaiting").hidden = !open.length; $("pillWaiting").textContent = `${open.length} waiting on a pick`;
    $("decisionList").innerHTML = open.map(s => sheetHtml(s)).join("") || `<span class="tiny muted">nothing is waiting on anyone. suspicious.</span>`;
    const done = await api("/api/sheets?place=leftovers");
    $("leftoverList").innerHTML = done.slice(0, 60).map(s => cardHtml(s, { where: display(s.fridge) })).join("") || `<span class="tiny muted">nothing finished yet. the kitchen is new.</span>`;
    if (done.length > 60) $("leftoverList").insertAdjacentHTML("beforeend", `<p class="tiny muted">and ${done.length - 60} more, on their fridges.</p>`);
    wire($("decisionList")); wire($("leftoverList")); wireGalleries($("decisionList"));
  } catch (e) { $("decisionList").innerHTML = `<p class="muted">${escapeHtml(why(e))}</p>`; }
}
function display(name) { const f = (KITCHEN && KITCHEN.fridges || []).find(f => f.name === name); return f ? f.display : name; }

// ── the house: settings a person changes from the page ──────────────────────
let SETTINGS = null;
async function upload(path, file) {
  const headers = { "Content-Type": file.type || "font/ttf" }, tok = getToken();
  if (tok) headers.Authorization = "Bearer " + tok;
  const r = await fetch(path, { method: "POST", headers, body: file });
  if (!r.ok) { let d = `${r.status}`; try { d = (await r.json()).detail || d; } catch (_) { /* not JSON */ } throw new Error(d); }
  return r.json();
}

async function loadSettings() {
  try { SETTINGS = await api("/api/settings"); } catch (e) { say("fontMsg", why(e), true); return; }
  const s = SETTINGS, y = s.yaml;
  const slotWords = { name: "the repo names on the freezers", freezer: "the release and build on the freezers", hand: "the notes (the house hand)" };
  $("fontRows").innerHTML = ["name", "freezer", "hand"].map(slot => {
    const state = s.fonts[slot] ? `uploaded: ${escapeHtml(s.fonts[slot])}` : y.fonts[slot] ? "from the yaml" : "system fallback";
    return `<div class="row font-row"><span class="lab">${slot}</span><span class="tiny dim" style="min-width:150px">${state}</span>` +
      `<input type="file" data-slot="${slot}" accept=".ttf,.otf,.woff,.woff2,font/ttf,font/otf,font/woff,font/woff2">` +
      (s.fonts[slot] ? `<button class="small" data-drop-slot="${slot}">remove</button>` : "") + `<span class="tiny muted">${escapeHtml(slotWords[slot])}</span></div>`;
  }).join("");
  const hands = Object.entries(s.fonts.hands || {});
  $("handRows").innerHTML = hands.map(([a, f]) => `<div class="row"><span class="lab">${escapeHtml(a)}</span><span class="tiny dim">${escapeHtml(f)}</span><button class="small" data-drop-hand="${escapeHtml(a)}">remove</button></div>`).join("")
    + (y.hands || []).filter(a => !s.fonts.hands[a]).map(a => `<div class="row"><span class="lab">${escapeHtml(a)}</span><span class="tiny dim">from the yaml</span></div>`).join("")
    || `<p class="tiny muted">no hands yet; everyone writes in the house hand.</p>`;
  $("fontRows").querySelectorAll("input[type=file]").forEach(inp => inp.onchange = async () => {
    const f = inp.files[0]; if (!f) return;
    try { await upload(`/api/settings/fonts/${inp.dataset.slot}`, f); say("fontMsg", `${inp.dataset.slot}: ${f.name} is on. reload to see it everywhere.`); await loadSettings(); }
    catch (e) { say("fontMsg", e.message, true); }
  });
  $("fontRows").querySelectorAll("[data-drop-slot]").forEach(b => b.onclick = async () => { try { await api(`/api/settings/fonts/${b.dataset.dropSlot}`, { method: "DELETE" }); await loadSettings(); } catch (e) { say("fontMsg", why(e), true); } });
  $("handRows").querySelectorAll("[data-drop-hand]").forEach(b => b.onclick = async () => { try { await api(`/api/settings/fonts/hand/${encodeURIComponent(b.dataset.dropHand)}`, { method: "DELETE" }); await loadSettings(); await loadWall(); } catch (e) { say("fontMsg", why(e), true); } });
  // github
  const gh = s.github, yg = y.github;
  $("ghStatus").textContent = gh.token_set ? "token: set, kept as a file in the state folder" : yg.token_env_set ? `token: from the yaml's env var ${yg.token_env}` : "no token: 60 calls an hour";
  $("ghInterval").value = gh.interval_minutes != null ? gh.interval_minutes : yg.interval_minutes;
  $("ghEnabled").checked = gh.enabled != null ? gh.enabled : yg.enabled;
  // the house
  $("housePerson").value = s.house.person || ""; $("housePerson").placeholder = y.house.person || "the person";
  $("housePartner").value = s.house.partner || ""; $("housePartner").placeholder = y.house.partner || "the partner";
  $("sourDays").value = s.sour_after_days != null ? s.sour_after_days : y.sour_after_days;
  $("houseNotesAt").value = s.house.notes_at || "top"; $("houseHinge").value = s.house.hinge || "right";
  // the fridges, in wall order
  const wall = (KITCHEN && KITCHEN.fridges) || [];
  const hidden = new Set(s.fridges.hidden || []);
  const all = wall.slice();
  for (const h of hidden) { if (!all.find(f => f.name === h)) all.push({ name: h, display: h, group: "", accent: "#999999", repo: "", counts: {} }); }
  $("fridgeRows").innerHTML = all.map((f, i) => `<div class="row fridge-row" data-name="${f.name}">` +
    `<button class="ghost" data-up="${f.name}" title="up">▲</button><button class="ghost" data-down="${f.name}" title="down">▼</button>` +
    `<input type="color" data-k="accent" value="${f.accent}" title="colour"><input data-k="display" value="${escapeHtml(f.display)}" maxlength="40" style="width:150px">` +
    `<input data-k="group" value="${escapeHtml(f.group || "")}" maxlength="20" style="width:90px"><input data-k="repo" value="${escapeHtml(f.repo || "")}" placeholder="owner/repo" style="flex:1">` +
    `<label class="row" style="margin:0"><input type="checkbox" data-k="hidden" ${hidden.has(f.name) ? "checked" : ""}> <span class="lab tiny">hidden</span></label>` +
    `<span class="tiny dim" style="min-width:90px">${escapeHtml(f.name)}</span></div>`).join("");
  $("fridgeRows").querySelectorAll(".fridge-row").forEach(row => {
    row.querySelectorAll("input").forEach(inp => inp.onchange = async () => {
      const k = inp.dataset.k, v = inp.type === "checkbox" ? inp.checked : inp.value;
      try { await api(`/api/settings/fridges/${row.dataset.name}`, { method: "PATCH", body: JSON.stringify({ [k]: v }) }); say("fridgeMsg", `${row.dataset.name}: ${k} saved.`); await loadWall(); if (k === "hidden") await loadSettings(); }
      catch (e) { say("fridgeMsg", await detail(e, `/api/settings`), true); }
    });
  });
  const move = async (name, dir) => {
    const order = [...$("fridgeRows").querySelectorAll(".fridge-row")].map(r => r.dataset.name);
    const i = order.indexOf(name), j = i + dir;
    if (j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
    try { await api("/api/settings/order", { method: "POST", body: JSON.stringify({ order }) }); await loadWall(); await loadSettings(); } catch (e) { say("fridgeMsg", why(e), true); }
  };
  $("fridgeRows").querySelectorAll("[data-up]").forEach(b => b.onclick = () => move(b.dataset.up, -1));
  $("fridgeRows").querySelectorAll("[data-down]").forEach(b => b.onclick = () => move(b.dataset.down, 1));
}

function wireSettings() {
  $("newHandGo").onclick = async () => {
    const a = $("newHandName").value.trim(), f = $("newHandFile").files[0];
    if (!a || !f) { say("fontMsg", "a name and a font file, both.", true); return; }
    try { await upload(`/api/settings/fonts/hand/${encodeURIComponent(a)}`, f); say("fontMsg", `${a}'s hand is on.`); $("newHandName").value = ""; $("newHandFile").value = ""; await loadSettings(); await loadWall(); }
    catch (e) { say("fontMsg", e.message, true); }
  };
  $("ghTokenGo").onclick = async () => {
    try { const r = await api("/api/settings/github", { method: "POST", body: JSON.stringify({ token: $("ghToken").value }) }); $("ghToken").value = ""; say("ghMsg", r.token_set ? "token saved to the state folder. it will not be shown again." : "token forgotten."); await loadSettings(); }
    catch (e) { say("ghMsg", await detail(e, "/api/settings"), true); }
  };
  $("ghGo").onclick = async () => {
    try { await api("/api/settings/github", { method: "POST", body: JSON.stringify({ interval_minutes: Number($("ghInterval").value), enabled: $("ghEnabled").checked }) }); say("ghMsg", "saved."); }
    catch (e) { say("ghMsg", why(e), true); }
  };
  $("houseGo").onclick = async () => {
    try {
      await api("/api/settings/house", { method: "POST", body: JSON.stringify({ person: $("housePerson").value, partner: $("housePartner").value, notes_at: $("houseNotesAt").value, hinge: $("houseHinge").value }) });
      await api("/api/settings/sour", { method: "POST", body: JSON.stringify({ days: Number($("sourDays").value) }) });
      say("houseMsg", "saved."); await loadWall();
    } catch (e) { say("houseMsg", why(e), true); }
  };
  $("nfGo").onclick = async () => {
    try {
      await api("/api/settings/fridges", { method: "POST", body: JSON.stringify({ name: $("nfName").value, display: $("nfDisplay").value, group: $("nfGroup").value, accent: $("nfAccent").value, repo: $("nfRepo").value }) });
      say("fridgeMsg", `${$("nfName").value} is on the wall.`); $("nfName").value = ""; $("nfDisplay").value = ""; $("nfRepo").value = ""; await loadWall(); await loadSettings();
    } catch (e) { say("fridgeMsg", await detail(e, "/api/settings"), true); }
  };
}

// ── small things in the kitchen that nobody is told about ───────────────────
const KONAMI = ["ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight", "b", "a"];
let KEYS = [];
document.addEventListener("keydown", e => {
  KEYS.push(e.key); KEYS = KEYS.slice(-KONAMI.length);
  if (KEYS.join() === KONAMI.join()) {
    document.querySelectorAll(".fridge .door").forEach((d, i) => { d.classList.add("swing"); setTimeout(() => d.classList.remove("swing"), 1800 + i * 40); });
    toast("every door at once. the cold is getting out.");
  }
});
function lateHour() { const h = new Date().getHours(); return h >= 1 && h < 5; }
function pinOfTitle(s, pin) { return /cheese/i.test(s.title || "") ? "cheese" : pin; }

// ── the cheese ───────────────────────────────────────────────────────────────
function cheese() {
  CHEESE += 1;
  const lines = ["don't touch the cheese.", "i said don't.", "that's the last slice.", "it's for later.", "...fine. one slice.", "you're impossible. 🧀"];
  toast(lines[Math.min(CHEESE - 1, lines.length - 1)]);
  if (CHEESE >= lines.length) { $("cheese").textContent = "🫙"; $("cheese").title = "the jar. it's empty. you did this."; }
}

document.addEventListener("DOMContentLoaded", () => {
  whoAmI(false);
  applyTidy();
  wireSettings();
  $("sheetClose").onclick = () => { $("sheetDlg").close(); SHOWN = null; };
  $("lvGo").onclick = leaveSheet;
  $("lvCancel").onclick = () => $("leaveDlg").close();
  $("oLeave").onclick = () => openLeave();
  $("houseLeave").onclick = () => { OPEN = (KITCHEN && KITCHEN.house && KITCHEN.house.fridge) || "seren-project"; openLeave(); };
  $("oBack").onclick = () => showTab("wall");
  $("fridgeEmpty").onclick = () => showTab("wall");
  $("oDrawerPull").onclick = () => {
    const open = $("oDrawerInside").hidden;                  // pulling a closed drawer opens it
    $("oDrawerInside").hidden = !open; $("oDrawer").classList.toggle("open", open);
    try { localStorage.setItem("kitchen.drawer", open ? "open" : "shut"); } catch (_) { /* a private window */ }
  };
  $("cheese").onclick = cheese;
  $("sheetDlg").addEventListener("close", () => { SHOWN = null; });
  $("freezerNow").onclick = async () => { try { const r = await api("/api/freezer/refresh", { method: "POST" }); toast(`freezer: ${r.read} read from GitHub${Object.keys(r.unreadable).length ? `, ${Object.keys(r.unreadable).length} unreadable` : ""}`); await loadWall(); } catch (e) { toast(why(e)); } };
  // #fridge=seren-memory opens that fridge straight away: a link to a fridge is a thing you can send,
  // on a fresh load and when the hash changes under an open page; #sheet=<id> opens a sheet
  const fromHash = () => {
    const m = /fridge=([\w-]+)/.exec(location.hash || ""); if (m) openFridge(m[1]);
    const s = /sheet=([0-9a-f]{12})/.exec(location.hash || ""); if (s) openSheet(s[1]);
  };
  startWatching();                                           // the first rounds are asked at once
  fromHash();                                                // a fridge in the hash becomes the fridge watch's question
  window.addEventListener("hashchange", fromHash);
  loadLists();
});
