const $ = s => document.querySelector(s);
const pad = n => String(n).padStart(2, "0");
const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const MONTHS = ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul", "Avgust", "Sentabr", "Oktyabr", "Noyabr", "Dekabr"];

// /app buyrug'i bergan havola: https://.../#key=XXXX&date=YYYY-MM-DD
const km = location.hash.match(/key=([^&]+)/);
const dm = location.hash.match(/date=(\d{4}-\d{2}-\d{2})/);
if (km) localStorage.locKey = decodeURIComponent(km[1]);
if (km || dm) history.replaceState(null, "", "/");

// ---------- Telefon xotirasi (IndexedDB): har bir kun alohida saqlanadi ----------
const idb = new Promise((res, rej) => {
  const r = indexedDB.open("locdiary", 1);
  r.onupgradeneeded = () => r.result.createObjectStore("days", { keyPath: "date" });
  r.onsuccess = () => res(r.result);
  r.onerror = () => rej(r.error);
});
const tx = async (mode, fn) => {
  const db = await idb;
  return new Promise((res, rej) => {
    const t = db.transaction("days", mode), req = fn(t.objectStore("days"));
    t.oncomplete = () => res(req.result);
    t.onerror = () => rej(t.error);
  });
};
const getDay = d => tx("readonly", s => s.get(d));
const putDay = rec => tx("readwrite", s => s.put(rec));
const allDays = () => tx("readonly", s => s.getAll());
if (navigator.storage?.persist) navigator.storage.persist(); // brauzer o'zi o'chirib yubormasin

async function api(path) {
  const r = await fetch(path, { headers: { "X-Key": localStorage.locKey || "" } });
  if (r.status === 401) {
    const k = prompt("Kirish kaliti (WEB_KEY):");
    if (!k) throw new Error("401");
    localStorage.locKey = k;
    return api(path);
  }
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

async function fetchDay(date) {
  const { trackers } = await api(`/api/points?date=${date}`);
  // o'tgan kun tugallangan: qayta yuklash shart emas. Bugun doim yangilanadi.
  const rec = { date, trackers, final: date < iso(new Date()), saved: Date.now() };
  await putDay(rec);
  return rec;
}

// ---------- Xarita ----------
const map = L.map("map").setView([41.3, 69.27], 12);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map);
const layer = L.layerGroup().addTo(map);
let date = dm ? dm[1] : iso(new Date());

// Nom va rang har safar serverdan yangilanadi (o'zgartirilsa eski kunlarda ham yangisi ko'rinadi)
let meta = JSON.parse(localStorage.locMeta || "{}");
const hidden = new Set();
let current = null;
const info = id => meta[id] || { name: `Joylashuv ${id}`, color: "#2563eb" };

async function refreshMeta() {
  try {
    meta = Object.fromEntries((await api("/api/trackers")).map(t => [t.id, t]));
    localStorage.locMeta = JSON.stringify(meta);
  } catch (e) { /* oflayn: saqlangan nomlar */ }
}

function render(rec, fit) {
  current = rec;
  layer.clearLayers();
  const list = $("#list"); list.innerHTML = "";
  const legend = $("#legend"); legend.innerHTML = "";
  const groups = rec.trackers;
  const nStops = groups.reduce((n, g) => n + g.stops.length, 0);
  $("#info").textContent = groups.length ? `${groups.length} joylashuv · ${nStops} joy` : "Ma'lumot yo'q";
  const all = [];

  groups.forEach(g => {
    const m = info(g.id), off = hidden.has(g.id);
    const chip = document.createElement("button");
    chip.className = "chip" + (off ? " off" : "");
    chip.style.setProperty("--c", m.color);
    chip.textContent = m.name;
    chip.onclick = () => { off ? hidden.delete(g.id) : hidden.add(g.id); render(rec, true); };
    legend.append(chip);
    if (off) return;

    const path = g.points.map(p => [p.lat, p.lon]);
    all.push(...path);
    L.polyline(path, { color: m.color, weight: 4, opacity: .85 }).addTo(layer);
    g.points.forEach(p => L.circleMarker([p.lat, p.lon], { radius: 3, color: m.color, weight: 1, fillColor: "#fff", fillOpacity: 1 })
      .bindTooltip(`${m.name} · ${p.t}`).addTo(layer));

    const h = document.createElement("li");
    h.className = "grp"; h.style.setProperty("--c", m.color); h.textContent = m.name;
    list.append(h);

    const markers = g.stops.map((st, i) => {
      const last = i === g.stops.length - 1;
      const icon = L.divIcon({ className: "", html: `<div class="pin${last ? " last" : ""}" style="background:${m.color};--c:${m.color}">${i + 1}</div>`, iconSize: [28, 28], iconAnchor: [14, 14] });
      const when = st.t0 === st.t1 ? st.t0 : `${st.t0}–${st.t1}`;
      const box = document.createElement("div");
      box.innerHTML = "<i></i><br><b></b><br><span></span>";
      box.children[0].textContent = m.name;
      box.children[0].style.color = m.color;
      box.children[2].textContent = st.dur ? `${when} · ${st.dur}` : when;
      box.children[4].textContent = st.addr;
      return L.marker([st.lat, st.lon], { icon }).bindPopup(box).addTo(layer);
    });

    g.stops.forEach((st, i) => {
      const li = document.createElement("li");
      const b = document.createElement("b");
      b.style.color = m.color;
      b.textContent = `${i + 1}. ${st.t0 === st.t1 ? st.t0 : st.t0 + "–" + st.t1}`;
      const d = document.createElement("span"); d.className = "dur"; d.textContent = st.dur ? ` (${st.dur})` : "";
      li.append(b, d, document.createElement("br"), document.createTextNode(st.addr));
      li.onclick = () => { map.flyTo([st.lat, st.lon], 18); markers[i].openPopup(); };
      list.append(li);
    });
  });
  if (fit && all.length) map.fitBounds(L.latLngBounds(all), { padding: [30, 30], maxZoom: 17 });
}

// ---------- Kunni ochish: avval telefondagi nusxa, keyin serverdan yangilash ----------
const rel = d => {
  const n = Math.round((new Date(iso(new Date())) - new Date(d)) / 864e5);
  if (n <= 0) return "Bugun";
  if (n === 1) return "Kecha";
  if (n < 30) return `${n} kun avval`;
  return `${Math.round(n / 30)} oy avval`;
};

async function load(fit = true) {
  const d = date;
  $("#title").textContent = `${rel(d)} · ${d}`;
  let cached = await getDay(d);
  if (cached && !cached.trackers) cached = null; // eski format - qayta yuklanadi
  if (cached) render(cached, fit);
  if (!cached?.final) {
    try {
      const rec = await fetchDay(d);
      if (d === date) render(rec, fit && !cached);
    } catch (e) {
      if (!cached) { layer.clearLayers(); $("#list").innerHTML = ""; $("#legend").innerHTML = ""; $("#info").textContent = "Oflayn: bu kun saqlanmagan"; }
    }
  }
}

function setDate(d) { date = d; $("#panel").hidden = true; load(); }
const shift = n => { const x = new Date(date); x.setDate(x.getDate() + n); setDate(iso(x)); };
$("#prev").onclick = () => shift(-1);
$("#next").onclick = () => shift(1);
$("#date").onchange = e => e.target.value && setDate(e.target.value);

// ---------- Kunlar ro'yxati (Bugun, Kecha, 4 kun avval, 1 oy avval ...) ----------
async function showPanel() {
  const cached = new Map((await allDays()).map(r => [r.date, r]));
  const server = JSON.parse(localStorage.locDays || "[]");
  const days = new Map(server.map(x => [x.date, x.n]));
  cached.forEach((r, d) => days.set(d, days.get(d) ?? (r.trackers || []).reduce((n, g) => n + g.points.length, 0)));
  days.set(iso(new Date()), days.get(iso(new Date())) ?? 0);
  const box = $("#panel .days"); box.innerHTML = "";
  let month = "";
  [...days].sort((a, b) => b[0].localeCompare(a[0])).forEach(([d, n]) => {
    const [y, m] = d.split("-");
    if (`${y}-${m}` !== month) {
      month = `${y}-${m}`;
      const h = document.createElement("h3"); h.textContent = `${y} ${MONTHS[+m - 1]}`; box.append(h);
    }
    const row = document.createElement("div");
    row.className = "day" + (d === date ? " sel" : "");
    const saved = cached.get(d)?.final ? " 📱" : "";
    row.innerHTML = "<span class=r></span><span class=d></span><span class=n></span>";
    row.children[0].textContent = rel(d);
    row.children[1].textContent = d.slice(5).replace("-", ".");
    row.children[2].textContent = `${n} nuqta${saved}`;
    row.onclick = () => setDate(d);
    box.append(row);
  });
  $("#panel").hidden = false;
}
$("#daysBtn").onclick = showPanel;
$("#close").onclick = () => $("#panel").hidden = true;

// ---------- Fon sinxronlash: barcha o'tgan kunlarni telefonga yuklab qo'yish ----------
async function sync() {
  try {
    await refreshMeta();
    const days = await api("/api/days");
    localStorage.locDays = JSON.stringify(days);
    const today = iso(new Date());
    for (const { date: d } of days) {
      if (d >= today) continue;
      const have = await getDay(d);
      if (!(have?.trackers && have.final)) await fetchDay(d);
    }
  } catch (e) { /* oflayn: mavjud nusxalar bilan ishlayveramiz */ }
}

setInterval(() => { if (!document.hidden && date === iso(new Date())) load(false); }, 60000);
refreshMeta().then(() => load()).then(sync);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
