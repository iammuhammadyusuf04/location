const $ = s => document.querySelector(s);
const pad = n => String(n).padStart(2, "0");
const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

// /app buyrug'i bergan havola: https://.../#key=XXXX
const m = location.hash.match(/key=([^&]+)/);
if (m) { localStorage.locKey = decodeURIComponent(m[1]); }
const dm = location.hash.match(/date=(\d{4}-\d{2}-\d{2})/);
if (m || dm) history.replaceState(null, "", "/");

const map = L.map("map").setView([41.3, 69.27], 12);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: "© OpenStreetMap"
}).addTo(map);
const layer = L.layerGroup().addTo(map);
$("#date").value = dm ? dm[1] : iso(new Date());

async function load(fit = true) {
  const date = $("#date").value;
  let r = await fetch(`/api/points?date=${date}`, { headers: { "X-Key": localStorage.locKey || "" } });
  if (r.status === 401) {
    const k = prompt("Kirish kaliti (WEB_KEY):");
    if (!k) return;
    localStorage.locKey = k;
    return load(fit);
  }
  const { points, stops } = await r.json();
  layer.clearLayers();
  const list = $("#list"); list.innerHTML = "";
  $("#info").textContent = stops.length ? `${stops.length} ta joy` : "Ma'lumot yo'q";
  if (!stops.length) return;

  // yo'l chizig'i + har bir yozilgan nuqta (kichik)
  const path = points.map(p => [p.lat, p.lon]);
  L.polyline(path, { color: "#1e66f5", weight: 4, opacity: .8 }).addTo(layer);
  points.forEach(p => L.circleMarker([p.lat, p.lon], { radius: 3, color: "#1e66f5", weight: 1, fillColor: "#fff", fillOpacity: 1 })
    .bindTooltip(p.t).addTo(layer));

  // to'xtash joylari: raqamlangan markerlar, tooltipda vaqt va davomiylik
  const markers = stops.map((st, i) => {
    const color = i === 0 ? "#16a34a" : i === stops.length - 1 ? "#dc2626" : "#1e66f5";
    const icon = L.divIcon({
      className: "",
      html: `<div class="pin" style="background:${color}">${i + 1}</div>`,
      iconSize: [28, 28], iconAnchor: [14, 14]
    });
    const when = st.t0 === st.t1 ? st.t0 : `${st.t0}–${st.t1}`;
    const box = document.createElement("div");
    box.innerHTML = "<b></b><br><span></span>";
    box.firstChild.textContent = st.dur ? `${when} · ${st.dur}` : when;
    box.lastChild.textContent = st.addr;
    return L.marker([st.lat, st.lon], { icon }).bindPopup(box).addTo(layer);
  });

  stops.forEach((st, i) => {
    const li = document.createElement("li");
    const b = document.createElement("b");
    b.textContent = `${i + 1}. ${st.t0 === st.t1 ? st.t0 : st.t0 + "–" + st.t1}`;
    const d = document.createElement("span"); d.className = "dur"; d.textContent = st.dur ? ` (${st.dur})` : "";
    li.append(b, d, document.createElement("br"), document.createTextNode(st.addr));
    li.onclick = () => { map.flyTo([st.lat, st.lon], 18); markers[i].openPopup(); };
    list.append(li);
  });
  if (fit) map.fitBounds(L.latLngBounds(path), { padding: [30, 30], maxZoom: 17 });
}

const shift = n => { const d = new Date($("#date").value); d.setDate(d.getDate() + n); $("#date").value = iso(d); load(); };
$("#prev").onclick = () => shift(-1);
$("#next").onclick = () => shift(1);
$("#date").onchange = () => load();
setInterval(() => { if (!document.hidden && $("#date").value === iso(new Date())) load(false); }, 60000);
load();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
