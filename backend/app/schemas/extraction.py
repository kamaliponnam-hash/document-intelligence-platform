"""
Pydantic schemas describing the shape of extracted field values, evidence
and financial validation checks. These are the building blocks used inside
the top-level document response (see schemas/document.py).
"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    source_text: Optional[str] = Field(
        default=None, description="Snippet of source text supporting the extracted value"
    )
    page_number: Optional[int] = Field(default=None, description="1-indexed page number")


class ExtractedField(BaseModel):
    """A single extracted key-value pair with optional grounding."""

    value: Optional[Any] = None
    confidence: Optional[float] = None  # OPTIONAL per spec
    page_number: Optional[int] = None
    evidence: Optional[Evidence] = None


class LineItem(BaseModel):
    """Invoice line item."""

    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    page_number: Optional[int] = None


class StatementItem(BaseModel):
    """
    Generic financial-statement line item, used for Balance Sheet / P&L /
    Cash Flow statements so that EVERY visible line (not just the minimum
    required fields) is captured, even though layouts vary widely between
    companies.
    """

    label: str
    current_period_value: Optional[float] = None
    comparative_period_value: Optional[float] = None
    current_period_label: Optional[str] = None
    comparative_period_label: Optional[str] = None
    page_number: Optional[int] = None


class ValidationCheck(BaseModel):
    name: str
    formula: str
    operands: dict[str, Optional[float]] = Field(default_factory=dict)
    calculated_value: Optional[float] = None
    reported_value: Optional[float] = None
    variance: Optional[float] = None
    status: str  # PASS | FAIL | NOT_APPLICABLE
    period: Optional[str] = None
    message: Optional[str] = None


class ValidationResult(BaseModel):
    checks: List[ValidationCheck] = Field(default_factory=list)
    overall_status: str = "NOT_APPLICABLE"  # PASS | FAIL | NOT_APPLICABLE
    issues: List[str] = Field(default_factory=list)
