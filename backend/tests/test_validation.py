import os

import pytest
from PIL import Image

from app.core.config import get_settings
from app.core.exceptions import CorruptedFileError, EmptyFileError, UnsupportedFileTypeError
from app.services.document_validation_service import DocumentValidationService
from app.services.financial_validation_service import FinancialValidationService


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def validation_service(settings):
    return DocumentValidationService(settings)


def _write_valid_png(path: str):
    img = Image.new("RGB", (200, 200), color="white")
    img.save(path)


def test_unsupported_extension_rejected(tmp_path, validation_service):
    file_path = tmp_path / "file.txt"
    file_path.write_text("hello")
    with pytest.raises(UnsupportedFileTypeError):
        validation_service.validate(str(file_path), "file.txt", None)


def test_empty_file_rejected(tmp_path, validation_service):
    file_path = tmp_path / "empty.png"
    file_path.write_bytes(b"")
    with pytest.raises(EmptyFileError):
        validation_service.validate(str(file_path), "empty.png", None)


def test_corrupted_pdf_rejected(tmp_path, validation_service):
    file_path = tmp_path / "bad.pdf"
    file_path.write_bytes(b"not a real pdf")
    with pytest.raises(CorruptedFileError):
        validation_service.validate(str(file_path), "bad.pdf", None)


def test_valid_png_passes(tmp_path, validation_service):
    file_path = tmp_path / "valid.png"
    _write_valid_png(str(file_path))
    result = validation_service.validate(str(file_path), "valid.png", None)
    assert result.status == "PASS"
    assert result.page_count == 1
    assert result.is_supported is True


# ---------------------------------------------------------------------
# Financial validation
# ---------------------------------------------------------------------
@pytest.fixture
def fin_service(settings):
    return FinancialValidationService(settings)


def _field(value):
    return {"value": value}


def test_invoice_total_check_pass(fin_service):
    fields = {
        "subtotal": _field(100.0),
        "tax_amount": _field(5.0),
        "discount": _field(0.0),
        "total_amount": _field(105.0),
    }
    result = fin_service.validate("invoice", fields)
    check = next(c for c in result.checks if c.name == "invoice_total_check")
    assert check.status == "PASS"
    assert result.overall_status == "PASS"


def test_invoice_total_check_fail(fin_service):
    fields = {
        "subtotal": _field(100.0),
        "tax_amount": _field(5.0),
        "discount": _field(0.0),
        "total_amount": _field(999.0),
    }
    result = fin_service.validate("invoice", fields)
    check = next(c for c in result.checks if c.name == "invoice_total_check")
    assert check.status == "FAIL"
    assert result.overall_status == "FAIL"


def test_invoice_total_check_not_applicable_when_missing_field(fin_service):
    fields = {
        "subtotal": _field(100.0),
        "tax_amount": _field(None),
        "discount": _field(0.0),
        "total_amount": _field(105.0),
    }
    result = fin_service.validate("invoice", fields)
    check = next(c for c in result.checks if c.name == "invoice_total_check")
    assert check.status == "NOT_APPLICABLE"


def test_balance_sheet_equation(fin_service):
    fields = {
        "total_assets": _field(1000.0),
        "total_liabilities": _field(600.0),
        "total_equity": _field(400.0),
    }
    result = fin_service.validate("balance_sheet", fields)
    assert result.overall_status == "PASS"


def test_cash_flow_checks(fin_service):
    fields = {
        "operating_cash_flow": _field(200.0),
        "investing_cash_flow": _field(-50.0),
        "financing_cash_flow": _field(-30.0),
        "net_change_in_cash": _field(120.0),
        "opening_cash": _field(50.0),
        "closing_cash": _field(170.0),
    }
    result = fin_service.validate("cash_flow_statement", fields)
    assert result.overall_status == "PASS"
    assert len(result.checks) == 2
