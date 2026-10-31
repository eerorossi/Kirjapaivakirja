// Kirjapäiväkirja – käyttöliittymä (vaihe 3: omat kirjaukset).
//
// Periaatteet:
// - Kaikki osoitteet ovat suhteellisia (api/..., static/...), jotta sovellus toimii
//   Caddyn polkuprefiksin (/kp) takana. Palvelin lisää sivulle <base href>.
// - Käyttäjän kirjoittama teksti piirretään aina DOM-solmuina (textContent), ei
//   koskaan innerHTML:llä, koska teksti näkyy vaiheessa 4 muille käyttäjille.

const SORTS = [
  ["newest", "Uusin"],
  ["title", "Kirjan nimi"],
  ["author", "Kirjailija"],
];
const SOURCE_NAMES = { finna: "Finna", openlibrary: "Open Library" };
const SPINES = ["#6b5b95", "#2f6f73", "#9a4d4d", "#5b7b3a", "#8a6a2f", "#3f5f8a"];
const SORT_KEY = "kp.sort";
const SVG_NS = "http://www.w3.org/2000/svg";

const appEl = document.getElementById("app");
const toastEl = document.getElementById("toast");
const navFeed = document.getElementById("nav-feed");
const navList = document.getElementById("nav-list");
const navNew = document.getElementById("nav-new");

let me = null;
let routeToken = 0;
let toastTimer = null;

// ---------- apufunktiot ----------

/** Luo DOM-solmu. Lapset ovat solmuja tai tekstiä (teksti ei koskaan tulkita HTML:nä). */
function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "value") el.value = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2).toLowerCase(), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

function fmtDate(iso) {
  const [y, m, d] = String(iso).split("-").map(Number);
  return `${d}.${m}.${y}`;
}

function fmtDateTime(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("fi-FI", { day: "numeric", month: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function countText(entry) {
  return [
    entry.like_count ? plural(entry.like_count, "peukku", "peukkua") : null,
    entry.comment_count ? plural(entry.comment_count, "kommentti", "kommenttia") : null,
  ].filter(Boolean).join(" · ");
}

function today() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function loadSort() {
  try {
    const stored = localStorage.getItem(SORT_KEY);
    if (SORTS.some(([key]) => key === stored)) return stored;
  } catch { /* yksityinen selaus tms.: oletus kelpaa */ }
  return "newest";
}

function saveSort(sort) {
  try { localStorage.setItem(SORT_KEY, sort); } catch { /* ei haittaa */ }
}

function paragraphs(text) {
  return String(text).split(/\n{2,}/).map((part) => h("p", {}, part.trim())).filter(Boolean);
}

// ---------- API ----------

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function errorText(status) {
  if (status === 401) return "Kirjautuminen on vanhentunut. Lataa sivu uudelleen.";
  if (status === 403) return "Tämä kirjaus kuuluu toiselle käyttäjälle.";
  if (status === 404) return "Kohdetta ei löytynyt. Se on voitu poistaa.";
  if (status === 422) return "Tarkista syöttämäsi tiedot ja yritä uudelleen.";
  if (status === 502) {
    return "Kirjan tietoja ei saatu haettua lähteestä. Yritä hetken päästä uudelleen tai lisää kirja käsin.";
  }
  return "Tallennus tai haku epäonnistui palvelimella. Yritä uudelleen.";
}

async function api(path, { method = "GET", body, signal } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      signal,
      credentials: "same-origin",
      headers: body
        ? { Accept: "application/json", "Content-Type": "application/json" }
        : { Accept: "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("Yhteys palvelimeen ei toimi. Tarkista verkkoyhteys ja yritä uudelleen.", 0);
  }
  if (response.status === 204) return null;
  const type = response.headers.get("content-type") || "";
  if (!type.includes("application/json")) {
    // Istunto vanhentunut: Authelian kirjautumissivu palautuu JSONin sijaan.
    throw new ApiError(errorText(401), 401);
  }
  const data = await response.json();
  if (!response.ok) throw new ApiError(errorText(response.status), response.status);
  return data;
}

// ---------- ilmoitukset ----------

function toast(message, { error = false } = {}) {
  toastEl.textContent = message;
  toastEl.className = error ? "toast toast-error" : "toast";
  toastEl.setAttribute("role", error ? "alert" : "status");
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.hidden = true; }, error ? 8000 : 3500);
}

function showError(error) {
  if (error && error.name === "AbortError") return;
  toast((error && error.message) || "Jokin meni pieleen. Yritä uudelleen.", { error: true });
}

// ---------- pienet osat ----------

function starIcon(filled) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", filled ? "star star-on" : "star");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", "M12 2.5l2.9 6.1 6.6.8-4.9 4.6 1.3 6.6L12 17.3l-5.9 3.3 1.3-6.6-4.9-4.6 6.6-.8z");
  svg.append(path);
  return svg;
}

function starsLabel(n) {
  return n === 1 ? "Arvio: 1 tähti viidestä" : `Arvio: ${n} tähteä viidestä`;
}

function stars(n) {
  return h("span", { class: "stars", role: "img", "aria-label": starsLabel(n) },
    [1, 2, 3, 4, 5].map((i) => starIcon(i <= n)));
}

/** Tähtivalinta: napauta tähteä, napauta samaa uudelleen poistaaksesi arvion. */
function starInput(initial) {
  let value = initial || null;
  const buttons = [1, 2, 3, 4, 5].map((i) => h("button", {
    type: "button",
    class: "star-btn",
    "aria-label": i === 1 ? "1 tähti" : `${i} tähteä`,
    onclick: () => { value = value === i ? null : i; paint(); },
  }));
  const el = h("div", { class: "star-input", role: "group", "aria-labelledby": "l-rating" }, buttons);
  function paint() {
    buttons.forEach((button, index) => {
      button.replaceChildren(starIcon(value !== null && index + 1 <= value));
      button.setAttribute("aria-pressed", String(value === index + 1));
    });
  }
  paint();
  return { el, get value() { return value; } };
}

function spineColor(title) {
  let n = 0;
  for (const ch of String(title)) n = (n * 31 + ch.codePointAt(0)) >>> 0;
  return SPINES[n % SPINES.length];
}

function initials(title) {
  return String(title).trim().split(/\s+/).slice(0, 2)
    .map((word) => Array.from(word)[0] || "").join("").toUpperCase();
}

function coverFallback(box, book) {
  box.classList.add("cover-none");
  box.style.setProperty("--spine", spineColor(book.title));
  box.replaceChildren(h("span", { "aria-hidden": "true" }, initials(book.title)));
}

function cover(book, size) {
  const box = h("div", { class: size === "lg" ? "cover cover-lg" : "cover" });
  if (book.has_cover) {
    const img = h("img", { src: `api/books/${book.id}/cover`, alt: "", loading: "lazy", decoding: "async" });
    img.addEventListener("error", () => coverFallback(box, book));
    box.append(img);
  } else {
    coverFallback(box, book);
  }
  return box;
}

function field(labelText, id, control) {
  return h("div", { class: "field" }, h("label", { class: "label", for: id }, labelText), control);
}

/** Lähdelinkki: vain https-osoitteet hyväksytään. */
function sourceNote(url) {
  let parsed;
  try { parsed = new URL(url); } catch { return null; }
  if (parsed.protocol !== "https:") return null;
  const host = parsed.hostname;
  const wiki = host.endsWith("wikipedia.org");
  const name = wiki ? "Wikipedia" : host.endsWith("openlibrary.org") ? "Open Library" : host;
  return h("p", { class: "source-note" }, "Lähde: ",
    h("a", { href: parsed.href, target: "_blank", rel: "noopener noreferrer" }, name),
    wiki ? " (lisenssi CC BY-SA)" : null);
}

function bookHead(book) {
  return h("header", { class: "book-head" },
    cover(book, "lg"),
    h("div", { class: "book-head-text" },
      h("h2", { class: "book-title-lg", tabindex: "-1" }, book.title),
      h("p", { class: "book-author" }, book.author),
      book.year ? h("p", { class: "muted" }, String(book.year)) : null));
}

function bookInfo(book, { openSummary = false } = {}) {
  const bio = book.author_bio
    ? h("details", { class: "fold" },
        h("summary", {}, "Kirjailijasta"),
        h("div", { class: "fold-body" }, paragraphs(book.author_bio),
          book.author_bio_source ? sourceNote(book.author_bio_source) : null))
    : null;
  const summary = book.summary
    ? h("details", { class: "fold", open: openSummary },
        h("summary", {}, "Kirjan kuvaus"),
        h("div", { class: "fold-body" }, paragraphs(book.summary),
          book.summary_source ? sourceNote(book.summary_source) : null))
    : null;
  if (!summary && !bio && !book.isbn) return null;
  return h("div", { class: "info" }, summary, bio,
    book.isbn ? h("p", { class: "muted" }, `ISBN ${book.isbn}`) : null);
}

/** Kirjauksen lomake (uusi ja muokkaus). */
function entryForm(initial, { submitLabel, busyLabel, onSubmit }) {
  const date = h("input", { type: "date", id: "f-date", name: "read_on", required: true, value: initial.read_on });
  const rating = starInput(initial.rating);
  const note = h("textarea", {
    id: "f-note", name: "note", rows: "6", maxlength: "20000",
    placeholder: "Mitä ajattelit kirjasta?",
  });
  note.value = initial.note || "";
  const submit = h("button", { type: "submit", class: "btn btn-primary" }, submitLabel);
  const form = h("form", { class: "form" },
    field("Lukupäivä", "f-date", date),
    h("div", { class: "field" },
      h("span", { class: "label", id: "l-rating" }, "Arvio (valinnainen)"),
      rating.el,
      h("p", { class: "hint" }, "Napauta tähteä. Napauta samaa uudelleen, jos haluat poistaa arvion.")),
    field("Muistiinpano", "f-note", note),
    submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!date.value) {
      toast("Valitse lukupäivä.", { error: true });
      date.focus();
      return;
    }
    submit.disabled = true;
    submit.textContent = busyLabel;
    try {
      await onSubmit({ read_on: date.value, note: note.value, rating: rating.value });
    } catch (error) {
      showError(error);
      submit.disabled = false;
      submit.textContent = submitLabel;
    }
  });
  return form;
}

// ---------- näkymät ----------

function rowLink(entry, { counts = false } = {}) {
  return h("a", { class: "row", href: `#/entry/${entry.id}` },
    cover(entry.book),
    h("div", { class: "row-body" },
      h("p", { class: "book-title" }, entry.book.title),
      h("p", { class: "book-author" }, entry.book.author),
      h("div", { class: "row-meta" },
        h("span", { class: "stamp" }, fmtDate(entry.read_on)),
        entry.rating ? stars(entry.rating) : null),
      entry.note ? h("p", { class: "note-clamp" }, entry.note) : null,
      counts && countText(entry) ? h("p", { class: "row-counts" }, countText(entry)) : null));
}

function entryRow(entry) {
  return h("li", {}, rowLink(entry, { counts: true }));
}

/** Peukutuspainike: päivittää kirjauksen tilan palvelimen vastauksella. */
function likeButton(entry) {
  const label = h("span", {});
  const count = h("span", { class: "like-count" });
  const button = h("button", { type: "button", class: "like-btn" }, label, count);
  const paint = () => {
    button.setAttribute("aria-pressed", String(entry.liked_by_me));
    button.classList.toggle("like-on", entry.liked_by_me);
    label.textContent = entry.liked_by_me ? "Peukutettu" : "Peukuta";
    count.textContent = entry.like_count ? String(entry.like_count) : "";
  };
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const state = await api(`api/entries/${entry.id}/like`, { method: entry.liked_by_me ? "DELETE" : "PUT" });
      entry.liked_by_me = state.liked;
      entry.like_count = state.like_count;
      paint();
    } catch (error) {
      showError(error);
    } finally {
      button.disabled = false;
    }
  });
  paint();
  return button;
}

function feedRow(entry) {
  const mine = entry.user_id === me.id;
  return h("li", { class: "feed-item" },
    h("p", { class: "row-user" }, mine ? "Sinä" : entry.user_name),
    rowLink(entry),
    h("div", { class: "social-bar" },
      mine ? h("span", { class: "muted" }, countText(entry) || "Ei vielä peukkuja tai kommentteja") : likeButton(entry),
      h("a", { class: "btn btn-quiet btn-small", href: `#/entry/${entry.id}` },
        entry.comment_count ? `Kommentit (${entry.comment_count})` : "Kommentoi")));
}

async function renderFeed(_args, ctx) {
  const first = await api("api/feed");
  let next = first.next_before;
  const list = h("ul", { class: "shelf" }, first.entries.map(feedRow));
  const more = h("button", { type: "button", class: "btn btn-quiet more", hidden: next === null }, "Näytä lisää");
  more.addEventListener("click", async () => {
    more.disabled = true;
    try {
      const page = await api(`api/feed?before=${next}`);
      list.append(...page.entries.map(feedRow));
      next = page.next_before;
      more.hidden = next === null;
    } catch (error) {
      showError(error);
    } finally {
      more.disabled = false;
    }
  });
  const view = h("section", {},
    h("h2", { class: "view-title", tabindex: "-1" }, "Syöte"),
    first.entries.length
      ? [h("p", { class: "count" }, "Kaikkien kirjaukset, uusimmat ensin"), list, more]
      : h("div", { class: "empty" },
          h("p", { class: "empty-title" }, "Syöte on vielä tyhjä"),
          h("p", { class: "muted" }, "Kun joku kirjaa luetun kirjan, se näkyy täällä."),
          h("a", { class: "btn btn-primary", href: "#/new" }, "Lisää kirja")));
  ctx.mount(view, "Syöte");
}

/** Peukut ja kommentit kirjauksen sivulla. */
function socialSection(entry, comments, likers) {
  const mine = entry.user_id === me.id;
  const title = h("h4", { class: "comments-title" });
  const list = h("ul", { class: "comments" });
  const paintTitle = () => { title.textContent = `Kommentit (${comments.length})`; };

  const commentItem = (comment) => {
    const item = h("li", { class: "comment" },
      h("p", { class: "comment-head" },
        h("strong", {}, comment.user_name), " ",
        h("span", { class: "muted" }, fmtDateTime(comment.created_at))),
      h("p", { class: "comment-body" }, comment.body));
    if (comment.can_delete) {
      const remove = h("button", {
        type: "button",
        class: "btn btn-quiet btn-small",
        "aria-label": `Poista kommentti, kirjoittaja ${comment.user_name}`,
      }, "Poista");
      remove.addEventListener("click", async () => {
        if (!confirm("Poistetaanko tämä kommentti?")) return;
        remove.disabled = true;
        try {
          await api(`api/comments/${comment.id}`, { method: "DELETE" });
          comments = comments.filter((c) => c.id !== comment.id);
          item.remove();
          paintTitle();
        } catch (error) {
          showError(error);
          remove.disabled = false;
        }
      });
      item.append(remove);
    }
    return item;
  };
  list.append(...comments.map(commentItem));
  paintTitle();

  const body = h("textarea", { id: "c-body", name: "body", maxlength: "2000", rows: "3", placeholder: "Kirjoita kommentti" });
  const submit = h("button", { type: "submit", class: "btn btn-primary" }, "Lähetä kommentti");
  const form = h("form", { class: "form comment-form" }, field("Oma kommentti", "c-body", body), submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!body.value.trim()) {
      toast("Kirjoita ensin kommentti.", { error: true });
      body.focus();
      return;
    }
    submit.disabled = true;
    submit.textContent = "Lähetetään…";
    try {
      const created = await api(`api/entries/${entry.id}/comments`, { method: "POST", body: { body: body.value } });
      comments = [...comments, created];
      list.append(commentItem(created));
      paintTitle();
      body.value = "";
    } catch (error) {
      showError(error);
    } finally {
      submit.disabled = false;
      submit.textContent = "Lähetä kommentti";
    }
  });

  return h("section", { class: "social" },
    h("h3", { class: "form-title" }, "Peukut ja kommentit"),
    mine
      ? h("p", { class: "muted" }, likers.length
          ? `Peukuttaneet: ${likers.map((l) => l.user_name).join(", ")}`
          : "Kukaan ei ole vielä peukuttanut tätä kirjausta.")
      : h("div", { class: "social-bar" }, likeButton(entry)),
    title, list, form);
}

function sortControl(current) {
  return h("div", { class: "segmented", role: "group", "aria-label": "Lajittelu" },
    SORTS.map(([key, label]) => h("button", {
      type: "button",
      class: key === current ? "seg seg-on" : "seg",
      "aria-pressed": String(key === current),
      onclick: () => { if (key !== current) { saveSort(key); route(); } },
    }, label)));
}

async function renderList(_args, ctx) {
  const sort = loadSort();
  const entries = await api(`api/entries?user_id=${me.id}&sort=${sort}`);
  const view = h("section", {},
    h("h2", { class: "view-title", tabindex: "-1" }, "Omat kirjaukset"),
    entries.length
      ? [
          h("p", { class: "count" }, `${entries.length} ${entries.length === 1 ? "kirjaus" : "kirjausta"}`),
          sortControl(sort),
          h("ul", { class: "shelf" }, entries.map(entryRow)),
        ]
      : h("div", { class: "empty" },
          h("p", { class: "empty-title" }, "Ei vielä kirjauksia"),
          h("p", { class: "muted" }, "Hae lukemasi kirja nimellä tai kirjailijalla ja kirjaa se muistiin."),
          h("a", { class: "btn btn-primary", href: "#/new" }, "Lisää ensimmäinen kirja")));
  ctx.mount(view, "Omat kirjaukset");
}

function resultRow(item, onPick, sourceLabel) {
  const byline = item.year ? `${item.author}, ${item.year}` : item.author;
  return h("li", {},
    h("button", { type: "button", class: "result", onclick: onPick },
      h("span", { class: "result-main" },
        h("span", { class: "book-title" }, item.title),
        h("span", { class: "book-author" }, byline)),
      sourceLabel ? h("span", { class: "source" }, sourceLabel) : null));
}

function group(title, items) {
  return h("section", { class: "group" },
    h("h3", { class: "group-title" }, title),
    h("ul", { class: "result-list" }, items));
}

function manualForm() {
  const title = h("input", { type: "text", id: "m-title", name: "title", required: true, maxlength: "300", autocomplete: "off" });
  const author = h("input", { type: "text", id: "m-author", name: "author", required: true, maxlength: "300", autocomplete: "off" });
  const year = h("input", { type: "number", id: "m-year", name: "year", inputmode: "numeric", min: "1", max: "2200" });
  const submit = h("button", { type: "submit", class: "btn btn-quiet" }, "Lisää kirja");
  const form = h("form", { class: "form" },
    field("Kirjan nimi", "m-title", title),
    field("Kirjailija", "m-author", author),
    field("Julkaisuvuosi (valinnainen)", "m-year", year),
    submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!title.value.trim() || !author.value.trim()) {
      toast("Kirjan nimi ja kirjailija ovat pakollisia.", { error: true });
      return;
    }
    submit.disabled = true;
    submit.textContent = "Lisätään…";
    try {
      const body = { title: title.value.trim(), author: author.value.trim() };
      if (year.value) body.year = Number(year.value);
      const book = await api("api/books", { method: "POST", body });
      location.hash = `#/new/${book.id}`;
    } catch (error) {
      showError(error);
      submit.disabled = false;
      submit.textContent = "Lisää kirja";
    }
  });
  return h("details", { class: "manual fold" },
    h("summary", {}, "Etkö löydä kirjaa? Lisää se käsin"),
    form);
}

async function renderSearch(_args, ctx) {
  const input = h("input", {
    type: "search", id: "q", name: "q", autocomplete: "off", autocapitalize: "off",
    enterkeyhint: "search", placeholder: "Kirjan nimi tai kirjailija",
  });
  const status = h("p", { class: "status", role: "status" });
  const results = h("div", { class: "results" });
  let timer = null;
  let controller = null;

  async function pick(item) {
    results.inert = true;
    status.textContent = "Tuodaan kirjan tietoja…";
    try {
      const book = await api("api/books/import", {
        method: "POST",
        body: { source: item.source, source_id: item.source_id },
      });
      location.hash = `#/new/${book.id}`;
    } catch (error) {
      results.inert = false;
      status.textContent = "";
      showError(error);
    }
  }

  async function run() {
    if (!ctx.current()) return;
    const q = input.value.trim();
    if (controller) controller.abort();
    if (q.length < 2) {
      results.replaceChildren();
      status.textContent = q ? "Kirjoita vähintään kaksi merkkiä." : "";
      return;
    }
    controller = new AbortController();
    const { signal } = controller;
    status.textContent = "Haetaan…";
    try {
      const encoded = encodeURIComponent(q);
      const [saved, found] = await Promise.all([
        api(`api/books?q=${encoded}`, { signal }),
        api(`api/books/search?q=${encoded}`, { signal }).catch((error) => {
          if (error.name === "AbortError") throw error;
          return { results: [], unavailable: [], failed: true };
        }),
      ]);
      const fresh = found.results.filter((r) => !saved.some((b) => b.source === r.source && b.source_id === r.source_id));
      // Huom: replaceChildren(null) kirjoittaisi sivulle tekstin "null", joten tyhjät suodatetaan.
      results.replaceChildren(...[
        saved.length
          ? group("Tallennetut kirjat", saved.map((b) => resultRow(b, () => { location.hash = `#/new/${b.id}`; })))
          : null,
        fresh.length
          ? group("Hakutulokset", fresh.map((r) => resultRow(r, () => pick(r), SOURCE_NAMES[r.source] || r.source)))
          : null,
      ].filter(Boolean));
      if (found.failed) {
        status.textContent = "Haku ei onnistunut. Voit valita tallennetuista kirjoista tai lisätä kirjan käsin.";
      } else if (found.unavailable.length) {
        const names = found.unavailable.map((s) => SOURCE_NAMES[s] || s).join(" ja ");
        status.textContent = `${names} ei vastannut, joten tulokset voivat olla vajaita.`;
      } else if (!saved.length && !fresh.length) {
        status.textContent = `Ei tuloksia haulle ”${q}”. Kokeile toista kirjoitusasua tai lisää kirja käsin.`;
      } else {
        status.textContent = "";
      }
    } catch (error) {
      if (error.name === "AbortError") return;
      status.textContent = "";
      showError(error);
    }
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(run, 400);
  });
  const form = h("form", { class: "search-form", role: "search" },
    field("Hae kirjaa", "q", input));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    clearTimeout(timer);
    run();
  });

  const view = h("section", {},
    h("h2", { class: "view-title", tabindex: "-1" }, "Lisää kirja"),
    form, status, results, manualForm());
  ctx.mount(view, "Lisää kirja");
  input.focus();
}

async function renderNewEntry([bookId], ctx) {
  const book = await api(`api/books/${bookId}`);
  const form = entryForm({ read_on: today() }, {
    submitLabel: "Tallenna kirjaus",
    busyLabel: "Tallennetaan…",
    onSubmit: async (data) => {
      await api("api/entries", { method: "POST", body: { book_id: book.id, ...data } });
      toast("Kirjaus tallennettu");
      location.hash = "#/";
    },
  });
  const view = h("section", {},
    h("a", { class: "back", href: "#/new" }, "Hae toinen kirja"),
    bookHead(book),
    bookInfo(book, { openSummary: true }),
    h("h3", { class: "form-title" }, "Oma kirjaus"),
    form);
  ctx.mount(view, book.title);
}

async function renderEntry([id], ctx) {
  const entry = await api(`api/entries/${id}`);
  const mine = entry.user_id === me.id;
  const [book, comments, likers] = await Promise.all([
    api(`api/books/${entry.book.id}`),
    api(`api/entries/${entry.id}/comments`),
    mine ? api(`api/entries/${entry.id}/likes`).catch(() => []) : [],
  ]);
  const parts = [
    mine
      ? h("a", { class: "back", href: "#/" }, "Takaisin kirjauksiin")
      : h("a", { class: "back", href: "#/feed" }, "Takaisin syötteeseen"),
    bookHead(book),
    bookInfo(book),
  ];
  if (mine) {
    const form = entryForm(entry, {
      submitLabel: "Tallenna muutokset",
      busyLabel: "Tallennetaan…",
      onSubmit: async (data) => {
        await api(`api/entries/${entry.id}`, { method: "PUT", body: data });
        toast("Muutokset tallennettu");
        location.hash = "#/";
      },
    });
    const remove = h("button", { type: "button", class: "btn btn-danger" }, "Poista kirjaus");
    remove.addEventListener("click", async () => {
      if (!confirm("Poistetaanko tämä kirjaus? Sitä ei voi palauttaa.")) return;
      remove.disabled = true;
      try {
        await api(`api/entries/${entry.id}`, { method: "DELETE" });
        toast("Kirjaus poistettu");
        location.hash = "#/";
      } catch (error) {
        showError(error);
        remove.disabled = false;
      }
    });
    parts.push(
      h("h3", { class: "form-title" }, "Oma kirjaus"), form, h("div", { class: "actions" }, remove),
      socialSection(entry, comments, likers));
  } else {
    parts.push(
      h("h3", { class: "form-title" }, `Kirjaus: ${entry.user_name}`),
      h("div", { class: "row-meta" },
        h("span", { class: "stamp" }, fmtDate(entry.read_on)),
        entry.rating ? stars(entry.rating) : null),
      entry.note ? h("p", { class: "note-full" }, entry.note) : null,
      socialSection(entry, comments, likers));
  }
  ctx.mount(h("section", {}, parts), book.title);
}

// ---------- reititys ----------

const ROUTES = [
  [/^#\/?$/, renderList],
  [/^#\/feed$/, renderFeed],
  [/^#\/new$/, renderSearch],
  [/^#\/new\/(\d+)$/, renderNewEntry],
  [/^#\/entry\/(\d+)$/, renderEntry],
];

function makeContext(token) {
  return {
    current: () => token === routeToken,
    mount(node, title) {
      if (token !== routeToken) return; // käyttäjä ehti jo toiseen näkymään
      appEl.replaceChildren(node);
      document.title = title ? `${title} – Kirjapäiväkirja` : "Kirjapäiväkirja";
      window.scrollTo(0, 0);
      const target = node.querySelector("[tabindex='-1']");
      if (target) target.focus({ preventScroll: true });
    },
  };
}

function markNav(hash) {
  // Kirjauksen sivu perii sen välilehden, josta tultiin (syöte tai omat kirjaukset).
  if (hash.startsWith("#/entry/") && document.querySelector(".tab-on")) return;
  const active = hash.startsWith("#/new") ? navNew : hash === "#/feed" ? navFeed : navList;
  for (const tab of [navFeed, navList, navNew]) {
    const on = tab === active;
    tab.classList.toggle("tab-on", on);
    if (on) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
}

function showProblem(error) {
  const gone = error && error.status === 404;
  appEl.replaceChildren(h("div", { class: "problem" },
    h("p", { class: "problem-title" }, gone ? "Kirjausta ei löytynyt" : "Sivua ei saatu ladattua"),
    h("p", {}, (error && error.message) || "Jokin meni pieleen."),
    gone
      ? h("a", { class: "btn btn-primary", href: "#/" }, "Takaisin kirjauksiin")
      : h("button", { type: "button", class: "btn btn-primary", onclick: () => location.reload() }, "Lataa sivu uudelleen")));
}

async function route() {
  const token = ++routeToken;
  const hash = location.hash || "#/";
  const ctx = makeContext(token);
  for (const [pattern, render] of ROUTES) {
    const match = hash.match(pattern);
    if (!match) continue;
    markNav(hash);
    appEl.setAttribute("aria-busy", "true");
    try {
      await render(match.slice(1).map(Number), ctx);
    } catch (error) {
      if (token === routeToken && error.name !== "AbortError") showProblem(error);
    } finally {
      if (token === routeToken) appEl.removeAttribute("aria-busy");
    }
    return;
  }
  location.hash = "#/";
}

async function boot() {
  try {
    me = await api("api/me");
  } catch (error) {
    showProblem(error);
    return;
  }
  document.getElementById("whoami").textContent = me.display_name;
  window.addEventListener("hashchange", route);
  route();
}

boot();
