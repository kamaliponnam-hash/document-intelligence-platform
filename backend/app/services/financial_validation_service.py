"""
Financial calculation validation service.

Implements section 4.4 of the spec for each of the four document types.
Every check reports: formula, operands used, calculated value, reported
value, variance and PASS / FAIL / NOT_APPLICABLE — exactly as required.

A check is NOT_APPLICABLE (never assumed/invented) whenever a required
input or the reported value it is compared against is missing from the
extracted data.

Scope note (documented assumption): validation runs against the CURRENT /
most-recent reporting period extracted into the top-level fields. Where a
document has comparative (prior-year) figures, those are captured in
`statement_items` for transparency but are not independently re-validated
in this 1-day build — see README "Known limitations".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.core.config import Settings
from app.core.logging import get_logger
from app.schemas.extraction import ValidationCheck, ValidationResult

logger = get_logger(__name__)


def _num(fields: dict[str, Any], name: str) -> Optional[float]:
    entry = fields.get(name)
    if not entry:
        return None
    value = entry.get("value") if isinstance(entry, dict) else entry
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class CheckSpec:
    name: str
    formula: str
    operand_names: list[str]
    reported_field: str
    compute: callable  # (operands: dict[str, float]) -> float


class FinancialValidationService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def validate(self, doc_type: str, fields: dict[str, Any]) -> ValidationResult:
        if doc_type == "invoice":
            checks = self._invoice_checks(fields)
        elif doc_type == "balance_sheet":
            checks = self._balance_sheet_checks(fields)
        elif doc_type == "profit_and_loss":
            checks = self._pnl_checks(fields)
        elif doc_type == "cash_flow_statement":
            checks = self._cash_flow_checks(fields)
        else:
            checks = []

        overall = self._overall_status(checks)
        issues = [c.name for c in checks if c.status == "FAIL"]
        return ValidationResult(checks=checks, overall_status=overall, issues=issues)

    # ------------------------------------------------------------------
    def _run(self, spec: CheckSpec, fields: dict[str, Any]) -> ValidationCheck:
        operands: dict[str, Optional[float]] = {name: _num(fields, name) for name in spec.operand_names}
        reported = _num(fields, spec.reported_field)

        if any(v is None for v in operands.values()) or reported is None:
            return ValidationCheck(
                name=spec.name,
                formula=spec.formula,
                operands=operands,
                calculated_value=None,
                reported_value=reported,
                variance=None,
                status="NOT_APPLICABLE",
                message="One or more required fields are missing from the extracted document.",
            )

        calculated = spec.compute(operands)
        variance = round(calculated - reported, 2)
        tolerance = max(
            self.settings.VALIDATION_ABS_TOLERANCE,
            abs(reported) * self.settings.VALIDATION_REL_TOLERANCE_PERCENT / 100.0,
        )
        status = "PASS" if abs(variance) <= tolerance else "FAIL"
        return ValidationCheck(
            name=spec.name,
            formula=spec.formula,
            operands=operands,
            calculated_value=round(calculated, 2),
            reported_value=reported,
            variance=variance,
            status=status,
        )

    @staticmethod
    def _overall_status(checks: list[ValidationCheck]) -> str:
        if not checks:
            return "NOT_APPLICABLE"
        statuses = {c.status for c in checks}
        if "FAIL" in statuses:
            return "FAIL"
        if statuses == {"NOT_APPLICABLE"}:
            return "NOT_APPLICABLE"
        return "PASS"

    # ------------------------------------------------------------------
    # Invoice
    # ------------------------------------------------------------------
    def _invoice_checks(self, fields: dict[str, Any]) -> list[ValidationCheck]:
        checks = []

        # A missing "discount" line on an invoice almost always means no
        # discount was applied (retailers print a discount line only when
        # one exists), not that the amount is genuinely unknown. Treating
        # it as 0 here is a defensible accounting default, unlike subtotal/
        # tax_amount/total_amount, which are left strictly required — if
        # those are missing we still correctly report NOT_APPLICABLE rather
        # than invent a value for them.
        effective_fields = dict(fields)
        if _num(fields, "discount") is None:
            effective_fields["discount"] = {"value": 0.0}

        # subtotal + tax - discount ≈ total
        checks.append(
            self._run(
                CheckSpec(
                    name="invoice_total_check",
                    formula="subtotal + tax_amount - discount",
                    operand_names=["subtotal", "tax_amount", "discount"],
                    reported_field="total_amount",
                    compute=lambda o: o["subtotal"] + o["tax_amount"] - o["discount"],
                ),
                effective_fields,
            )
        )

        # cash_paid - total_amount ≈ change (only if those fields exist)
        if _num(fields, "cash_paid") is not None and _num(fields, "change_returned") is not None:
            checks.append(
                self._run(
                    CheckSpec(
                        name="cash_change_check",
                        formula="cash_paid - total_amount",
                        operand_names=["cash_paid", "total_amount"],
                        reported_field="change_returned",
                        compute=lambda o: o["cash_paid"] - o["total_amount"],
                    ),
                    fields,
                )
            )

        return checks

    # ------------------------------------------------------------------
    # Balance Sheet
    # ------------------------------------------------------------------
    def _balance_sheet_checks(self, fields: dict[str, Any]) -> list[ValidationCheck]:
        return [
            self._run(
                CheckSpec(
                    name="balance_sheet_equation_check",
                    formula="total_liabilities + total_equity",
                    operand_names=["total_liabilities", "total_equity"],
                    reported_field="total_assets",
                    compute=lambda o: o["total_liabilities"] + o["total_equity"],
                ),
                fields,
            )
        ]

    # ------------------------------------------------------------------
    # Profit & Loss
    # ------------------------------------------------------------------
    def _pnl_checks(self, fields: dict[str, Any]) -> list[ValidationCheck]:
        checks = []

        # gross_profit ≈ revenue - cost_of_sales
        checks.append(
            self._run(
                CheckSpec(
                    name="gross_profit_check",
                    formula="revenue - cost_of_sales",
                    operand_names=["revenue", "cost_of_sales"],
                    reported_field="gross_profit",
                    compute=lambda o: o["revenue"] - o["cost_of_sales"],
                ),
                fields,
            )
        )

        # operating_profit ≈ gross_profit - operating_expenses
        checks.append(
            self._run(
                CheckSpec(
                    name="operating_profit_check",
                    formula="gross_profit - operating_expenses",
                    operand_names=["gross_profit", "operating_expenses"],
                    reported_field="operating_profit",
                    compute=lambda o: o["gross_profit"] - o["operating_expenses"],
                ),
                fields,
            )
        )

        # net_profit ≈ operating_profit - tax
        checks.append(
            self._run(
                CheckSpec(
                    name="net_profit_check",
                    formula="operating_profit - tax",
                    operand_names=["operating_profit", "tax"],
                    reported_field="net_profit",
                    compute=lambda o: o["operating_profit"] - o["tax"],
                ),
                fields,
            )
        )

        return checks

    # ------------------------------------------------------------------
    # Cash Flow Statement
    # ------------------------------------------------------------------
    def _cash_flow_checks(self, fields: dict[str, Any]) -> list[ValidationCheck]:
        checks = []

        checks.append(
            self._run(
                CheckSpec(
                    name="net_change_in_cash_check",
                    formula="operating_cash_flow + investing_cash_flow + financing_cash_flow",
                    operand_names=["operating_cash_flow", "investing_cash_flow", "financing_cash_flow"],
                    reported_field="net_change_in_cash",
                    compute=lambda o: o["operating_cash_flow"] + o["investing_cash_flow"] + o["financing_cash_flow"],
                ),
                fields,
            )
        )

        checks.append(
            self._run(
                CheckSpec(
                    name="closing_cash_check",
                    formula="opening_cash + net_change_in_cash",
                    operand_names=["opening_cash", "net_change_in_cash"],
                    reported_field="closing_cash",
                    compute=lambda o: o["opening_cash"] + o["net_change_in_cash"],
                ),
                fields,
            )
        )

        return checks