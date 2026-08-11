let currentTab = "pending";
let currentSlug = null;
let queueCache = [];

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s ?? "";
  return div.innerHTML;
}

async function loadQueue() {
  const res = await fetch("/api/queue");
  queueCache = await res.json();
  renderList();
}

function renderList() {
  document.getElementById("detail").classList.add("hidden");
  document.getElementById("list").classList.remove("hidden");

  const items = queueCache.filter((i) => i.status === currentTab);
  const list = document.getElementById("list");

  if (items.length === 0) {
    list.innerHTML = `<div class="empty">Nothing here.</div>`;
    return;
  }

  list.innerHTML = items
    .map((item) => {
      const flags = [];
      if (item.suppressed) flags.push('<span class="badge warn">suppressed</span>');
      if (item.already_sent) flags.push('<span class="badge">already sent</span>');
      return `
        <div class="row" data-slug="${escapeHtml(item.slug)}">
          <div class="row-main">
            <h3>${escapeHtml(item.business_name)}</h3>
            <div class="meta">${escapeHtml(item.city)}, ${escapeHtml(item.state)}</div>
            <div class="subject">"${escapeHtml(item.subject)}"</div>
          </div>
          <div class="flags">${flags.join("")}</div>
        </div>`;
    })
    .join("");

  list.querySelectorAll(".row").forEach((row) => {
    row.addEventListener("click", () => selectLead(row.dataset.slug));
  });
}

async function selectLead(slug) {
  currentSlug = slug;
  const res = await fetch(`/api/lead/${encodeURIComponent(slug)}`);
  const data = await res.json();
  renderDetail(data);
}

function renderDetail(data) {
  document.getElementById("list").classList.add("hidden");
  const detail = document.getElementById("detail");
  detail.classList.remove("hidden");

  const flags = [];
  if (data.suppressed) flags.push('<span class="badge warn">On the suppression list -- do not contact</span>');
  if (data.already_sent) flags.push('<span class="badge">Initial send already recorded</span>');
  if (!data.demo_exists) flags.push('<span class="badge warn">No demo site generated yet</span>');
  if (!data.dossier_exists) flags.push('<span class="badge">No dossier generated yet</span>');

  const followupsHtml = (data.draft.followups || [])
    .map(
      (f, i) => `
      <div class="followup">
        <h4>Follow-up ${i + 1} -- Day ${f.day_offset}</h4>
        <div><strong>${escapeHtml(f.subject)}</strong></div>
        <div class="body-text">${escapeHtml(f.body)}</div>
      </div>`
    )
    .join("");

  const decisionNote =
    data.status !== "pending"
      ? `<div class="decision-note">Status: <strong>${data.status.toUpperCase()}</strong>${data.notes ? " -- " + escapeHtml(data.notes) : ""}</div>`
      : "";

  detail.innerHTML = `
    <button class="back" id="back-btn">&larr; Back to queue</button>
    <h2>${escapeHtml(data.business_name)}</h2>
    <div class="meta">${escapeHtml(data.city)}, ${escapeHtml(data.state)} -- ${escapeHtml(data.phone || "no phone on file")} -- ${escapeHtml(data.qualification_status || "")}</div>
    <div class="flags">${flags.join("")}</div>

    <h4>Subject</h4>
    <div class="body-text">${escapeHtml(data.draft.subject_line)}</div>

    <h4>Email Body</h4>
    <div class="body-text">${escapeHtml(data.draft.email_body)}</div>

    <h4>SMS</h4>
    <div class="body-text">${escapeHtml(data.draft.sms_body)}</div>

    ${followupsHtml}

    ${decisionNote}

    <div class="actions">
      <div style="width:100%;">
        <textarea id="notes-input" placeholder="Optional notes (e.g. why rejected, or what to fix before resending)">${escapeHtml(data.notes || "")}</textarea>
      </div>
      <button class="btn approve" id="approve-btn">Approve</button>
      <button class="btn reject" id="reject-btn">Reject</button>
      ${data.status !== "pending" ? '<button class="btn reset" id="reset-btn">Reset to pending</button>' : ""}
    </div>
  `;

  document.getElementById("back-btn").addEventListener("click", () => renderList());
  document.getElementById("approve-btn").addEventListener("click", () => decide(data.slug, data.business_name, "approved"));
  document.getElementById("reject-btn").addEventListener("click", () => decide(data.slug, data.business_name, "rejected"));
  const resetBtn = document.getElementById("reset-btn");
  if (resetBtn) resetBtn.addEventListener("click", () => resetDecision(data.slug));
}

async function decide(slug, business_name, status) {
  const notes = document.getElementById("notes-input").value;
  await fetch("/api/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slug, business_name, status, notes }),
  });
  await loadQueue();
}

async function resetDecision(slug) {
  await fetch("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slug }),
  });
  await loadQueue();
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    currentTab = tab.dataset.status;
    renderList();
  });
});

loadQueue();
