const $ = (s) => document.querySelector(s),
  esc = (v) =>
    String(v ?? "—").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
const names = {
  restricted_intrusion: "Restricted intrusion",
  loitering: "Loitering",
  abandoned_object: "Possible abandoned object",
  wrong_direction: "Wrong direction",
  vehicle_entry: "Vehicle entry",
};
const when = (v) =>
  v
    ? new Date(v).toLocaleString([], {
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "—";
const score = (v) => (v == null ? "Unknown" : `${Math.round(v * 100)}%`);
let state = { health: { metrics: {} }, world: [], cameras: [], incidents: [] },
  filters = { type: "", camera: "" },
  rendering = false;
async function get(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw Error(`${path}: ${r.status}`);
  return r.json();
}
function showError(e) {
  $("#error").hidden = false;
  $("#error").textContent = `Unable to complete the request. ${e.message}`;
}
function row(i) {
  return `<tr><td><a href="#incident/${encodeURIComponent(i.incident_id)}">${esc(names[i.type] || i.type)}</a><div style="font-size:10px;color:#858a80;margin-top:5px">${esc(i.incident_id.slice(0, 8))} · ${i.synthetic ? "Synthetic" : "Camera observation"}</div></td><td>${esc(i.cameras.join(", "))}</td><td>${esc(when(i.end_time || i.start_time))}</td><td><span class="tag ${i.severity === "high" ? "high" : ""}">${esc(i.severity)}</span></td><td>${score(i.confidence)}</td><td><span class="tag ${i.evidence_status === "ready" ? "" : "pending"}">${esc(i.evidence_status)}</span></td><td><a href="#incident/${encodeURIComponent(i.incident_id)}" aria-label="View ${esc(names[i.type])}">View ↗</a></td></tr>`;
}
function table(items) {
  return `<div class="panel scroll"><table><thead><tr><th>INCIDENT</th><th>CAMERA</th><th>OBSERVED AT</th><th>SEVERITY</th><th>CONFIDENCE</th><th>EVIDENCE</th><th></th></tr></thead><tbody>${items.map(row).join("")}</tbody></table>${items.length ? "" : '<div class="empty">No incidents match this view.</div>'}</div>`;
}
function camera(c) {
  const tracks = state.world.filter((t) => t.camera_id === c.camera_id);
  return `<article class="camera"><div class="camera-head"><span>${esc(c.camera_id)}</span><span class="tag">${esc(c.status || "Unknown")}</span></div><div class="viewport">${
    c.preview_evidence_id
      ? `<video controls muted playsinline preload="metadata" src="/evidence/${encodeURIComponent(c.preview_evidence_id)}"></video>`
      : `<svg viewBox="0 0 640 360" role="img" aria-label="Normalized track positions"><defs><pattern id="grid-${esc(c.camera_id)}" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M 40 0 L 0 0 0 40" fill="none" stroke="#33423c" stroke-width=".5"/></pattern></defs><rect width="640" height="360" fill="url(#grid-${esc(c.camera_id)})"/>${tracks
          .map((t) => {
            const [a, b, x, y] = t.bbox;
            return `<rect x="${a * 640}" y="${b * 360}" width="${(x - a) * 640}" height="${(y - b) * 360}" fill="#8baa6518" stroke="#bacf92"/><text x="${a * 640}" y="${b * 360 - 7}" fill="#dce9bf" font-size="11">${esc(t.local_track_id)}</text>`;
          })
          .join("")}</svg>`
  }<span class="overlay-label">${c.preview_evidence_id ? "SAVED EVIDENCE / " + (state.health.mode === "synthetic" ? "SYNTHETIC" : "RECORDED") : "TRACK MAP / NO CAMERA VIDEO"}</span></div><div class="camera-foot"><span>${tracks.length} active tracks</span><span>${esc(c.fps == null ? "FPS unavailable" : c.fps + " FPS")}</span></div></article>`;
}
function live() {
  const h = state.health;
  return `<section class="heading"><div><div class="eyebrow">OPERATIONS OVERVIEW</div><h1>Every observation matters.</h1><p>Current tracks, incident signals, and the evidence behind them.</p></div><a class="button" href="#incidents">View incidents ↗</a></section><div class="stats">${[
    ["Cameras", state.cameras.length, "Configured observation sources"],
    [
      "Current entities",
      state.world.length,
      h.mode === "synthetic"
        ? "At the end of the saved replay"
        : "Tracks inside the freshness window",
    ],
    ["Incidents", h.incidents ?? 0, "Candidates available for review"],
    [
      "Processing",
      h.metrics.last_processing_ms == null
        ? "—"
        : h.metrics.last_processing_ms + " ms",
      "Latest observation processing time",
    ],
  ]
    .map(
      ([label, value, note]) =>
        `<div class="stat"><small>${label}</small><strong>${esc(value)}</strong><em>${esc(note)}</em></div>`,
    )
    .join(
      "",
    )}</div><div class="section-head"><h2>Camera overview</h2><span>${h.mode === "synthetic" ? "Saved synthetic scenarios" : "Observation sources"}</span></div><div class="camera-grid">${state.cameras.slice(0, 4).map(camera).join("") || '<div class="empty">No observations received. Run the demo or connect a producer.</div>'}</div><div class="section-head"><h2>Recent incidents</h2><a class="back" href="#incidents">View all →</a></div>${table(state.incidents.slice(0, 5))}<div class="section-head"><h2>World state</h2><span>Local tracks · cross-camera identities stay separate</span></div><div class="panel scroll"><table><thead><tr><th>TRACK</th><th>CAMERA</th><th>ZONE</th><th>DWELL</th><th>MOVEMENT</th><th>LAST SEEN</th></tr></thead><tbody>${state.world.map((t) => `<tr><td>${esc(t.local_track_id)}</td><td>${esc(t.camera_id)}</td><td>${esc(t.zone)}</td><td>${t.dwell_time.toFixed(1)} s</td><td>${esc(t.movement_state)}</td><td>${esc(when(t.last_seen))}</td></tr>`).join("")}</tbody></table></div>`;
}
function incidents() {
  return `<section class="heading"><div><div class="eyebrow">INCIDENT WORKSPACE</div><h1>Signals worth a closer look.</h1><p>Inspect the timeline, understand the rule, and review the evidence.</p></div><span class="pill">${state.incidents.length} shown / ${state.health.incidents ?? 0} total</span></section><div class="filters"><label>Event type<br><select id="type-filter"><option value="">All event types</option>${Object.entries(
    names,
  )
    .map(
      ([k, v]) =>
        `<option value="${k}" ${filters.type === k ? "selected" : ""}>${v}</option>`,
    )
    .join(
      "",
    )}</select></label><label>Camera<br><select id="camera-filter"><option value="">All cameras</option>${state.cameras.map((c) => `<option value="${esc(c.camera_id)}" ${filters.camera === c.camera_id ? "selected" : ""}>${esc(c.camera_id)}</option>`).join("")}</select></label></div>${table(state.incidents.filter((i) => (!filters.type || i.type === filters.type) && (!filters.camera || i.cameras.includes(filters.camera))))}`;
}
async function detail(id) {
  const i = await get("/incidents/" + encodeURIComponent(id)),
    e = i.evidence[0];
  return `<section class="heading"><div><a class="back" href="#incidents">← All incidents</a><div class="eyebrow" style="margin-top:24px">INCIDENT / ${esc(id.slice(0, 8))}</div><h1>${esc(names[i.type] || i.type)}</h1><p>${esc(i.cameras.join(" · "))} &nbsp; / &nbsp; ${esc(when(i.end_time))}</p></div><span class="tag high">${esc(i.review_decision || "AWAITING REVIEW")}</span></section><div class="detail-grid"><div><div class="panel">${e ? `<video class="detail-video" controls playsinline preload="metadata" src="/evidence/${encodeURIComponent(e.evidence_id)}"></video>` : '<div class="empty">Evidence is pending. No playable clip has been registered.</div>'}<div class="padded"><div class="section-head" style="margin-top:0"><h2>Evidence</h2><span>${i.synthetic ? "Synthetic demonstration" : "Recorded source"}</span></div><p>${e ? `Preserved clip · ${esc(e.duration_seconds?.toFixed(1) || "unknown")} seconds · ${esc(e.coverage || "coverage unreported")}` : "The incident remains available while evidence capture completes."}</p>${e ? `<div class="source-id">SHA-256 ${esc(e.sha256)}</div>` : ""}</div></div><div class="panel padded"><h2>Why this alert fired</h2>${i.reasons.map((r) => `<div class="reason">${esc(r)}</div>`).join("")}<p style="font-size:11px">Rule ${esc(i.rule_version)} · Model ${esc(i.model_version)}</p></div><div class="panel padded"><h2>Observation timeline</h2><div class="reason">${esc(when(i.start_time))} · Rule window starts</div><div class="reason">${esc(when(i.end_time))} · Candidate raised</div><p style="font-size:11px">Supporting observation IDs</p>${i.source_observation_ids.map((x) => `<div class="source-id">${esc(x)}</div>`).join("")}</div></div><div><div class="panel padded"><h2>Incident facts</h2><dl class="facts"><div><dt>CAMERA</dt><dd>${esc(i.cameras.join(", "))}</dd></div><div><dt>CONFIDENCE</dt><dd>${score(i.confidence)}</dd></div><div><dt>STATUS</dt><dd>${esc(i.status)}</dd></div><div><dt>EVIDENCE</dt><dd>${esc(i.evidence_status)}</dd></div></dl><p style="font-size:11px">Involved local entities</p>${i.involved_entities.map((x) => `<div class="source-id">${esc(x)}</div>`).join("")}${i.plate ? `<div class="reason">Plate ${esc(i.plate.text)} · ${score(i.plate.confidence)}</div>` : ""}</div><div class="panel padded"><h2>Optional verification</h2><div class="reason">${esc(i.verification?.summary || "No VLM inference requested. The deterministic rule works independently.")}</div><span class="tag">${esc(i.verification_status)}</span></div><div class="panel padded"><h2>Operator review</h2><p style="font-size:11px;margin-top:8px">Record your assessment after checking the evidence.</p><label for="failure">Failure reason, if relevant</label><select id="failure" style="width:100%;margin-top:8px"><option value="">None</option>${["detector", "tracker", "cross-camera", "rule", "occlusion", "low light", "bad camera/input", "overload"].map((v) => `<option>${v}</option>`).join("")}</select><textarea id="note" rows="3" placeholder="Add context for the team" aria-label="Review note"></textarea><div class="review-actions">${["CONFIRMED", "FALSE", "UNCERTAIN"].map((v) => `<button data-review="${v}" data-id="${esc(id)}" class="${v === "CONFIRMED" ? "primary" : ""}">${v[0] + v.slice(1).toLowerCase()}</button>`).join("")}</div><div id="review-feedback" role="status"></div>${i.reviews.map((r) => `<p class="review-note"><b>${esc(r.decision)}</b> · ${esc(when(r.created_at))}<br><span>${esc(r.note)}</span></p>`).join("")}</div></div></div>`;
}
async function render() {
  if (rendering) return;
  rendering = true;
  try {
    const route = location.hash.slice(1) || "live";
    $("#nav-live").classList.toggle("active", route === "live");
    $("#nav-incidents").classList.toggle("active", route !== "live");
    $("#crumb").textContent =
      route === "live"
        ? "LIVE OPERATIONS"
        : route === "incidents"
          ? "INCIDENTS"
          : "INCIDENT DETAIL";
    $("#content").innerHTML = route.startsWith("incident/")
      ? await detail(decodeURIComponent(route.slice(9)))
      : route === "incidents"
        ? incidents()
        : live();
    $("#type-filter")?.addEventListener("change", (e) => {
      filters.type = e.target.value;
      render();
    });
    $("#camera-filter")?.addEventListener("change", (e) => {
      filters.camera = e.target.value;
      render();
    });
    document.querySelectorAll("[data-review]").forEach((b) =>
      b.addEventListener("click", async () => {
        b.disabled = true;
        try {
          await get(`/incidents/${encodeURIComponent(b.dataset.id)}/reviews`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              decision: b.dataset.review,
              note: $("#note").value,
              failure_reason: $("#failure").value || null,
            }),
          });
          await render();
        } catch (e) {
          showError(e);
          b.disabled = false;
        }
      }),
    );
  } catch (e) {
    showError(e);
  } finally {
    rendering = false;
  }
}
async function refresh() {
  try {
    const [health, world, cameras, incidents] = await Promise.all(
      ["/health", "/world", "/cameras", "/incidents?limit=500"].map((p) =>
        get(p),
      ),
    );
    state = { health, world, cameras, incidents };
    $("#nav-count").textContent = health.incidents;
    $("#mode").textContent =
      health.mode === "synthetic" ? "SYNTHETIC REPLAY" : "LIVE INGEST";
    $("#error").hidden = true;
    await render();
  } catch (e) {
    showError(e);
  }
}
let pending;
function connect() {
  const ws = new WebSocket(
    `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/live`,
  );
  ws.onopen = () => ($("#connection").textContent = "Updates connected");
  ws.onmessage = (event) => {
    if (
      location.hash.startsWith("#incident/") ||
      [...document.querySelectorAll("video")].some((v) => !v.paused)
    )
      return;
    const message = JSON.parse(event.data);
    if (
      message.type === "world" &&
      JSON.stringify(message.data) === JSON.stringify(state.world)
    )
      return;
    clearTimeout(pending);
    pending = setTimeout(refresh, 300);
  };
  ws.onclose = () => {
    $("#connection").textContent = "Reconnecting…";
    setTimeout(connect, 3000);
  };
  ws.onerror = () => ws.close();
}
window.addEventListener("hashchange", render);
setInterval(
  () =>
    ($("#clock").textContent = new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    })),
  1000,
);
refresh();
connect();
