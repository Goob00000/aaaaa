"use strict";

// ── State ──────────────────────────────────────────────────────────────────
let _currentResultId = null;

// ── Inline save (status dropdown) ─────────────────────────────────────────
async function saveField(resultId, field, value, el) {
  try {
    const resp = await fetch(`/results/${resultId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [field]: value }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    flashSave("Saved");
  } catch (err) {
    console.error(err);
    flashSave("Save failed — check console", true);
    if (el) el.blur();
  }
}

// ── Edit modal ─────────────────────────────────────────────────────────────
function openModal(id, question, answer, updatedBy, status) {
  _currentResultId = id;
  document.getElementById("modal-question").textContent   = question;
  document.getElementById("modal-answer").value           = answer;
  document.getElementById("modal-updated-by").value       = updatedBy;
  document.getElementById("modal-status").value           = status;
  bootstrap.Modal.getOrCreateInstance(document.getElementById("editModal")).show();
}

async function saveModal() {
  const answer    = document.getElementById("modal-answer").value;
  const updatedBy = document.getElementById("modal-updated-by").value;
  const status    = document.getElementById("modal-status").value;

  try {
    const resp = await fetch(`/results/${_currentResultId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ draft_answer: answer, updated_by: updatedBy, review_status: status }),
    });
    if (!resp.ok) throw new Error(await resp.text());

    // Refresh the row preview in the table
    const preview = document.getElementById(`preview-${_currentResultId}`);
    if (preview) preview.textContent = answer.length > 100 ? answer.slice(0, 100) + "…" : answer;

    // Update status badge in row
    const row = document.getElementById(`row-${_currentResultId}`);
    if (row) {
      const sel = row.querySelector(".status-select");
      if (sel) sel.value = status;
    }

    bootstrap.Modal.getInstance(document.getElementById("editModal")).hide();
    flashSave("Changes saved");
  } catch (err) {
    console.error(err);
    flashSave("Save failed — check console", true);
  }
}

// ── Progress polling (job page while processing) ───────────────────────────
function pollProgress(jobId) {
  const bar   = document.getElementById("progress-bar");
  const label = document.getElementById("progress-label");
  if (!bar) return;

  const iv = setInterval(async () => {
    try {
      const data = await fetch(`/jobs/${jobId}/status`).then(r => r.json());
      const pct  = data.total > 0 ? Math.round((data.processed / data.total) * 100) : 0;

      bar.style.width = `${pct}%`;
      bar.setAttribute("aria-valuenow", pct);
      bar.textContent = `${pct}%`;
      if (label) label.textContent = `${data.processed} / ${data.total}`;

      if (data.status === "done" || data.status === "error") {
        clearInterval(iv);
        location.reload();
      }
    } catch (e) {
      // network hiccup — keep polling
    }
  }, 2000);
}

// ── Toast flash ────────────────────────────────────────────────────────────
function flashSave(msg, isError = false) {
  const el = document.createElement("div");
  el.className = `alert ${isError ? "alert-danger" : "alert-success"} shadow save-flash`;
  el.innerHTML = `<i class="bi bi-${isError ? "x-circle" : "check-circle"} me-2"></i>${msg}`;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}
