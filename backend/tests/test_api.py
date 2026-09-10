import io

from PIL import Image, ImageDraw


def _make_invoice_image_bytes() -> bytes:
    """Render a simple synthetic invoice image so OCR + offline extraction
    have something realistic to work with, without needing any external
    sample files or an LLM API key."""
    img = Image.new("RGB", (900, 500), color="white")
    draw = ImageDraw.Draw(img)
    lines = [
        "Invoice Number: INV-1001",
        "Invoice Date: 2026-01-15",
        "Vendor: Test Vendor Inc",
        "Customer: Test Customer LLC",
        "Currency: USD",
        "Sub Total: 200.00",
        "Tax Amount: 10.00",
        "Discount: 0.00",
        "Total Amount Due: 210.00",
    ]
    y = 20
    for line in lines:
        draw.text((20, y), line, fill="black")
        y += 40
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def test_health_endpoint(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"


def test_list_documents_empty_or_list(client):
    res = client.get("/api/v1/documents")
    assert res.status_code == 200
    body = res.json()
    assert "documents" in body
    assert isinstance(body["documents"], list)


def test_unsupported_file_type_rejected(client):
    res = client.post(
        "/api/v1/documents/process",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
        data={"document_type": "invoice"},
    )
    assert res.status_code == 415
    body = res.json()
    assert body["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_invalid_document_type_rejected(client):
    img_bytes = _make_invoice_image_bytes()
    res = client.post(
        "/api/v1/documents/process",
        files={"file": ("invoice.png", img_bytes, "image/png")},
        data={"document_type": "not_a_real_type"},
    )
    assert res.status_code == 400
    body = res.json()
    assert body["error"]["code"] == "INVALID_DOCUMENT_TYPE"


def test_empty_file_rejected(client):
    res = client.post(
        "/api/v1/documents/process",
        files={"file": ("empty.png", b"", "image/png")},
        data={"document_type": "invoice"},
    )
    assert res.status_code == 400
    body = res.json()
    assert body["error"]["code"] == "EMPTY_FILE"


def test_full_process_and_retrieve_flow(client):
    img_bytes = _make_invoice_image_bytes()
    res = client.post(
        "/api/v1/documents/process",
        files={"file": ("integration_test_invoice.png", img_bytes, "image/png")},
        data={"document_type": "invoice"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["document_name"] == "integration_test_invoice.png"
    assert body["document_type"] == "invoice"
    assert body["file_validation"]["status"] == "PASS"
    assert body["processing_status"] in {"PASS", "FAILED"}
    assert "extracted_data" in body
    assert "validation" in body

    # GET by name should return the same latest result
    get_res = client.get("/api/v1/documents/integration_test_invoice.png")
    assert get_res.status_code == 200
    get_body = get_res.json()
    assert get_body["document_name"] == "integration_test_invoice.png"

    # Should now appear in the list endpoint
    list_res = client.get("/api/v1/documents")
    names = [d["document_name"] for d in list_res.json()["documents"]]
    assert "integration_test_invoice.png" in names


def test_get_nonexistent_document_returns_404(client):
    res = client.get("/api/v1/documents/does_not_exist.pdf")
    assert res.status_code == 404
    body = res.json()
    assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"
