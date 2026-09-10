// Document Intelligence Platform — frontend logic.
// Talks to the same-origin backend REST API under /api/v1.

const API_BASE = "/api/v1";

function showError(msg) {
  const el = document.getElementById("error-banner");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("visible");
}

function clearError() {
  const el = document.getElementById("error-banner");
  if (!el) return;
  el.classList.remove("visible");
  el.textContent = "";
}

function fmtDate(iso) {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------
// Dashboard page
// ---------------------------------------------------------------------
async function initDashboard() {
  const form = document.getElementById("upload-form");
  const tableBody = document.getElementById("documents-body");
  const submitBtn = document.getElementById("submit-btn");
  const statusMsg = document.getElementById("upload-status");

  async function loadDocuments() {
    try {
      const res = await fetch(`${API_BASE}/documents`);
      const data = await res.json();
      if (!res.ok) throw new Error((data.error && data.error.message) || "Failed to load documents");
      tableBody.innerHTML = "";
      if (!data.documents.length) {
        tableBody.innerHTML = `<tr><td colspan="6" class="muted">No documents processed yet. Upload one above to get started.</td></tr>`;
        return;
      }
      for (const doc of data.documents) {
        const tr = document.createElement("tr");
        tr.className = "clickable";
        tr.onclick = () => (window.location.href = `/documents/${encodeURIComponent(doc.document_name)}`);
        tr.innerHTML = `
          <td>${doc.document_name}</td>
          <td>${doc.document_type}</td>
          <td><span class="badge ${doc.processing_status}">${doc.processing_status}</span></td>
          <td><span class="badge ${doc.overall_validation_status || "NOT_APPLICABLE"}">${doc.overall_validation_status || "N/A"}</span></td>
          <td>${doc.ocr_used ? "Yes" : "No"}</td>
          <td>${fmtDate(doc.processed_at)}</td>
        `;
        tableBody.appendChild(tr);
      }
    } catch (err) {
      showError(err.message);
    }
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearError();
    const fileInput = document.getElementById("file-input");
    const typeSelect = document.getElementById("document-type");

    if (!fileInput.files.length) {
      showError("Please choose a file to upload.");
      return;
    }

    const fd = new FormData();
    fd.append("file", fileInput.files[0]);
    fd.append("document_type", typeSelect.value);

    submitBtn.disabled = true;
    statusMsg.innerHTML = `<span class="spinner"></span> Processing document (OCR + AI extraction)... this can take up to a minute.`;

    try {
      const res = await fetch(`${API_BASE}/documents/process`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) {
        throw new Error((data.error && data.error.message) || "Processing failed.");
      }
      statusMsg.textContent = `Done. Status: ${data.processing_status}.`;
      fileInput.value = "";
      await loadDocuments();
      window.location.href = `/documents/${encodeURIComponent(data.document_name)}`;
    } catch (err) {
      statusMsg.textContent = "";
      showError(err.message);
    } finally {
      submitBtn.disabled = false;
    }
  });

  await loadDocuments();
}

// ---------------------------------------------------------------------
// Document result page
// ---------------------------------------------------------------------
async function initDocumentResult(documentName) {
  const container = document.getElementById("result-container");
  try {
    const res = await fetch(`${API_BASE}/documents/${encodeURIComponent(documentName)}`);
    const data = await res.json();
    if (!res.ok) throw new Error((data.error && data.error.message) || "Document not found.");
    renderResult(data);
  } catch (err) {
    showError(err.message);
    container.innerHTML = "";
  }
}

function renderResult(data) {
  document.getElementById("doc-title").textContent = data.document_name;
  document.getElementById("doc-type-badge").textContent = data.document_type;
  const statusBadge = document.getElementById("doc-status-badge");
  statusBadge.textContent = data.processing_status;
  statusBadge.className = `badge ${data.processing_status}`;

  if (data.error) {
    showError(`${data.error.code}: ${data.error.message}`);
  }

  // File validation
  const fv = data.file_validation || {};
  document.getElementById("file-validation").innerHTML = `
    <div class="kv-row"><span class="k">File type</span><span class="v">${fv.file_type || "-"}</span></div>
    <div class="kv-row"><span class="k">Supported</span><span class="v">${fv.is_supported ? "Yes" : "No"}</span></div>
    <div class="kv-row"><span class="k">Readable</span><span class="v">${fv.is_readable ? "Yes" : "No"}</span></div>
    <div class="kv-row"><span class="k">Page count</span><span class="v">${fv.page_count ?? "-"}</span></div>
    <div class="kv-row"><span class="k">Status</span><span class="v"><span class="badge ${fv.status}">${fv.status}</span></span></div>
  `;

  // Extracted fields (key-value, excluding line_items/statement_items/header)
  const extracted = data.extracted_data || {};
  const kvContainer = document.getElementById("extracted-fields");
  kvContainer.innerHTML = "";
  const skipKeys = new Set(["line_items", "statement_items", "header"]);
  const keys = Object.keys(extracted).filter((k) => !skipKeys.has(k));
  if (!keys.length) {
    kvContainer.innerHTML = `<p class="muted">No fields extracted.</p>`;
  }
  for (const key of keys) {
    const entry = extracted[key] || {};
    const missing = entry.value === null || entry.value === undefined;
    const row = document.createElement("div");
    row.className = `kv-row ${missing ? "missing" : ""}`;
    const evidence = entry.evidence && entry.evidence.source_text ? ` (p.${entry.evidence.page_number || "?"}: "${entry.evidence.source_text}")` : "";
    row.innerHTML = `<span class="k">${key.replace(/_/g, " ")}</span><span class="v" title="${evidence}">${missing ? "Missing" : entry.value}</span>`;
    kvContainer.appendChild(row);
  }

  // Line items / statement items table
  const tableSection = document.getElementById("items-section");
  const items = extracted.line_items && extracted.line_items.length ? extracted.line_items
    : (extracted.statement_items || []);
  if (items.length) {
    const isLineItems = !!(extracted.line_items && extracted.line_items.length);
    let html = "<table><thead><tr>";
    const cols = isLineItems
      ? ["description", "quantity", "unit_price", "amount"]
      : ["label", "current_period_value", "comparative_period_value"];
    cols.forEach((c) => (html += `<th>${c.replace(/_/g, " ")}</th>`));
    html += "</tr></thead><tbody>";
    for (const item of items) {
      html += "<tr>" + cols.map((c) => `<td>${item[c] ?? "-"}</td>`).join("") + "</tr>";
    }
    html += "</tbody></table>";
    tableSection.innerHTML = html;
  } else {
    tableSection.innerHTML = `<p class="muted">No line items / statement items extracted.</p>`;
  }

  // Financial validation
  const validation = data.validation || { checks: [] };
  const valSection = document.getElementById("validation-section");
  if (!validation.checks.length) {
    valSection.innerHTML = `<p class="muted">No applicable financial validations for this document.</p>`;
  } else {
    let html = "<table><thead><tr><th>Check</th><th>Formula</th><th>Calculated</th><th>Reported</th><th>Variance</th><th>Status</th></tr></thead><tbody>";
    for (const c of validation.checks) {
      html += `<tr>
        <td>${c.name}</td>
        <td class="muted">${c.formula}</td>
        <td>${c.calculated_value ?? "-"}</td>
        <td>${c.reported_value ?? "-"}</td>
        <td>${c.variance ?? "-"}</td>
        <td><span class="badge ${c.status}">${c.status}</span></td>
      </tr>`;
    }
    html += "</tbody></table>";
    if (validation.issues && validation.issues.length) {
      html += `<p class="muted" style="margin-top:12px;">Issues: ${validation.issues.join("; ")}</p>`;
    }
    valSection.innerHTML = html;
  }

  // Processing metadata
  const meta = data.processing_metadata || {};
  document.getElementById("processing-metadata").innerHTML = `
    <div class="kv-row"><span class="k">OCR used</span><span class="v">${meta.ocr_used ? "Yes" : "No"}</span></div>
    <div class="kv-row"><span class="k">Extraction mode</span><span class="v">${meta.extraction_mode || "-"}</span></div>
    <div class="kv-row"><span class="k">Model</span><span class="v">${meta.llm_model || "-"}</span></div>
    <div class="kv-row"><span class="k">Processed at</span><span class="v">${fmtDate(meta.processed_at)}</span></div>
    <div class="kv-row"><span class="k">Processing time</span><span class="v">${meta.processing_time_ms ?? "-"} ms</span></div>
  `;

  // Raw JSON
  document.getElementById("raw-json").textContent = JSON.stringify(data, null, 2);
}

function switchTab(tabId, btnEl) {
  document.querySelectorAll(".tab-panel").forEach((p) => (p.style.display = "none"));
  document.getElementById(tabId).style.display = "block";
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
  btnEl.classList.add("active");
}
