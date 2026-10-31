const $ = s => document.querySelector(s);
const pad = n => String(n).padStart(2, "0");
const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

// /app buyrug'i bergan havola: https://.../#key=XXXX
const m = location.hash.match(/key=([^&]+)/);
if (m) { localStorage.locKey = decodeURIComponent(m[1]); history.replaceState(null, "", "/"); }

const map = L.map("map").setView([41.3, 69.27], 12);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: "© OpenStreetMap"
}).addTo(map);
const layer = L.layerGroup().addTo(map);
$("#date").value = iso(new Date());

async function load(fit = true) {
  const date = $("#date").value;
  let r = await fetch(`/api/points?date=${date}`, { headers: { "X-Key": localStorage.locKey || "" } });
  if (r.status === 401) {
    const k = prompt("Kirish kaliti (WEB_KEY):");
    if (!k) return;
    localStorage.locKey = k;
    return load(fit);
  }
  const pts = await r.json();
  layer.clearLayers();
  const list = $("#list"); list.innerHTML = "";
  $("#info").textContent = pts.length ? `${pts.length} nuqta` : "Ma'lumot yo'q";
  if (!pts.length) return;

  const ll = pts.map(p => [p.lat, p.lon]);
  L.polyline(ll, { color: "#1e66f5", weight: 4 }).addTo(layer);
  const markers = pts.map((p, i) => {
    const color = i === 0 ? "#16a34a" : i === pts.length - 1 ? "#dc2626" : "#1e66f5";
    const mk = L.circleMarker(ll[i], { radius: i === pts.length - 1 ? 9 : 6, color: "#fff", weight: 2, fillColor: color, fillOpacity: 1 }).addTo(layer);
    const box = document.createElement("div");
    box.innerHTML = "<b></b><br><span></span>";
    box.firstChild.textContent = p.t; box.lastChild.textContent = p.addr;
    mk.bindPopup(box);
    return mk;
  });
  let prev = null;
  pts.forEach((p, i) => {
    if (p.addr === prev) return;
    prev = p.addr;
    const li = document.createElement("li");
    const b = document.createElement("b"); b.textContent = p.t;
    li.append(b, document.createTextNode(p.addr));
    li.onclick = () => { map.flyTo(ll[i], 17); markers[i].openPopup(); };
    list.append(li);
  });
  if (fit) map.fitBounds(L.latLngBounds(ll), { padding: [30, 30], maxZoom: 17 });
}

const shift = n => { const d = new Date($("#date").value); d.setDate(d.getDate() + n); $("#date").value = iso(d); load(); };
$("#prev").onclick = () => shift(-1);
$("#next").onclick = () => shift(1);
$("#date").onchange = () => load();
setInterval(() => { if (!document.hidden && $("#date").value === iso(new Date())) load(false); }, 60000);
load();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
