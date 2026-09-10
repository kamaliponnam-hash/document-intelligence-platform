import pytest

from app.core.config import get_settings
from app.services.extraction_service import ExtractionService
from app.services.ocr_service import ExtractionText, PageText

SAMPLE_INVOICE_TEXT = """
Invoice Number: INV-23891
Invoice Date: 2026-08-15
Vendor: ABC Technologies
Customer: Acme Corp
Currency: USD
Sub Total: 12500.00
Tax Amount: 625.00
Discount: 0.00
Total Amount Due: 13125.00
"""


@pytest.fixture
def service():
    return ExtractionService(get_settings())


def test_offline_extraction_finds_invoice_fields(service):
    ocr_result = ExtractionText(pages=[PageText(1, SAMPLE_INVOICE_TEXT, used_ocr=False)])
    outcome = service._extract_offline("invoice", ocr_result)
    fields = outcome["fields"]
    assert fields["invoice_number"]["value"] == "INV-23891"
    assert fields["subtotal"]["value"] == 12500.00
    assert fields["tax_amount"]["value"] == 625.00
    assert fields["total_amount"]["value"] == 13125.00


def test_offline_extraction_missing_fields_are_null(service):
    ocr_result = ExtractionText(pages=[PageText(1, "Some unrelated text with no labels.", used_ocr=False)])
    outcome = service._extract_offline("invoice", ocr_result)
    for field_name, entry in outcome["fields"].items():
        assert entry["value"] is None


def test_parse_json_response_plain():
    raw = '{"fields": {"a": {"value": 1}}}'
    parsed = ExtractionService._parse_json_response(raw)
    assert parsed["fields"]["a"]["value"] == 1


def test_parse_json_response_with_code_fence():
    raw = '```json\n{"fields": {"a": {"value": 2}}}\n```'
    parsed = ExtractionService._parse_json_response(raw)
    assert parsed["fields"]["a"]["value"] == 2


def test_parse_json_response_with_surrounding_prose():
    raw = 'Here is the result:\n{"fields": {"a": {"value": 3}}}\nHope that helps.'
    parsed = ExtractionService._parse_json_response(raw)
    assert parsed["fields"]["a"]["value"] == 3
