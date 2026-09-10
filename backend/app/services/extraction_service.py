"""
AI-based field & table extraction service.

Design
------
Financial documents have highly variable layouts (different vendors,
different statement formats, different currencies), so a fixed set of
regex rules cannot satisfy "extract ALL meaningful information visible in
the document" (section 4.2). We therefore use an LLM as the primary
extraction engine: it is given the full OCR/parsed text (page-tagged) plus
a document-type-specific instruction describing the minimum required
fields, and is asked to return ONLY a JSON object.

Provider
--------
Supports two interchangeable providers, selected via LLM_PROVIDER:
  * "gemini"    (default) — Google AI Studio / Gemini API, free tier
  * "anthropic" — Claude, requires paid API credits
Both are prompted identically and must return the same JSON shape, so the
rest of the pipeline is provider-agnostic.

Reliability / graceful degradation
-----------------------------------
* If no API key is configured for the selected provider, or the LLM call
  fails/times out, and ALLOW_OFFLINE_EXTRACTION_FALLBACK=true, we fall back
  to a lightweight regex/heuristic extractor so the service never crashes
  and still returns a best-effort structured result rather than a 5xx.
* The LLM is explicitly instructed never to invent values; missing fields
  must be returned as null. We do not post-hoc fabricate values either.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from app.core.config import Settings
from app.core.exceptions import ExtractionServiceError
from app.core.logging import get_logger
from app.services.ocr_service import ExtractionText
from app.utils.file_utils import parse_bracketed_number

logger = get_logger(__name__)

REQUIRED_FIELDS = {
    "invoice": [
        "invoice_number", "invoice_date", "vendor_name", "customer_name",
        "currency", "subtotal", "tax_amount", "discount", "total_amount",
    ],
    "balance_sheet": ["total_assets", "total_liabilities", "total_equity"],
    "profit_and_loss": [
        "revenue", "cost_of_sales", "gross_profit", "operating_expenses",
        "operating_profit", "tax", "net_profit",
    ],
    "cash_flow_statement": [
        "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
        "opening_cash", "net_change_in_cash", "closing_cash",
    ],
}

_DOC_TYPE_INSTRUCTIONS = {
    "invoice": """
This is an INVOICE. Extract header fields AND every line item in the table.
Minimum required top-level fields (use null if genuinely not present):
invoice_number, invoice_date (ISO format YYYY-MM-DD if determinable, else the
raw text), vendor_name, customer_name, currency (ISO code if possible, else
symbol/text as shown), subtotal, tax_amount, discount, total_amount.
Also extract, if present: payment_terms, due_date, cash_paid, change_returned,
tax_rate, po_number, billing_address, shipping_address.
Populate "line_items" as an array of {"description","quantity","unit_price",
"amount","page_number"} for every row in the item table.
""",
    "balance_sheet": """
This is a BALANCE SHEET. Extract header info (company_name, statement_date or
period_end dates, currency, reporting periods present e.g. current & prior
year) and:
Minimum required top-level fields (current/most-recent period), null if absent:
total_assets, total_liabilities, total_equity.
Also populate "statement_items": an array covering EVERY visible line item
(e.g. cash and cash equivalents, receivables, inventory, PP&E, payables,
borrowings, reserves & surplus, share capital, etc.) with
{"label","current_period_value","comparative_period_value",
"current_period_label","comparative_period_label","page_number"}.
Treat bracketed/parenthesised numbers as negative values.
""",
    "profit_and_loss": """
This is a PROFIT & LOSS / INCOME statement. Extract header info (company_name,
period(s) covered, currency) and:
Minimum required top-level fields (current/most-recent period), null if absent:
revenue, cost_of_sales (COGS), gross_profit, operating_expenses,
operating_profit, tax, net_profit.
Also populate "statement_items": an array covering EVERY visible income/expense
line (e.g. interest earned, other income, interest expended, provisions and
contingencies, total income, total expenditure, minority interest, EPS, etc.)
with {"label","current_period_value","comparative_period_value",
"current_period_label","comparative_period_label","page_number"}.
Treat bracketed/parenthesised numbers as negative values.
""",
    "cash_flow_statement": """
This is a CASH FLOW STATEMENT. Extract header info (company_name, period(s)
covered, currency) and:
Minimum required top-level fields (current/most-recent period), null if absent:
operating_cash_flow, investing_cash_flow, financing_cash_flow, opening_cash,
net_change_in_cash, closing_cash.
Also populate "statement_items": an array covering EVERY visible line item
(e.g. FX/translation adjustment, cash acquired on amalgamation, depreciation
add-back, working capital changes, etc.) with {"label",
"current_period_value","comparative_period_value","current_period_label",
"comparative_period_label","page_number"}.
Treat bracketed/parenthesised numbers as negative values (common for cash
outflows).
""",
}

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@dataclass
class ExtractionOutcome:
    data: dict[str, Any]
    mode: str  # "llm" | "offline_fallback"
    model: Optional[str] = None


class ExtractionService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def extract(self, doc_type: str, ocr_result: ExtractionText, document_name: str) -> ExtractionOutcome:
        text = ocr_result.full_text.strip()

        if not text:
            logger.warning("No text content available to extract from for %s", document_name)
            return ExtractionOutcome(data=self._empty_skeleton(doc_type), mode="offline_fallback")

        provider = self.settings.LLM_PROVIDER
        api_key = self.settings.GEMINI_API_KEY if provider == "gemini" else self.settings.ANTHROPIC_API_KEY
        model_name = self.settings.GEMINI_MODEL if provider == "gemini" else self.settings.ANTHROPIC_MODEL

        if api_key:
            try:
                data = self._extract_with_llm(doc_type, text, provider)
                return ExtractionOutcome(data=data, mode="llm", model=model_name)
            except Exception as exc:
                logger.exception("LLM extraction (%s) failed for %s: %s", provider, document_name, exc)
                if not self.settings.ALLOW_OFFLINE_EXTRACTION_FALLBACK:
                    raise ExtractionServiceError(
                        "AI extraction service failed and no fallback is enabled."
                    ) from exc
                logger.warning("Falling back to offline heuristic extraction for %s", document_name)
        else:
            logger.warning(
                "%s API key not configured; using offline heuristic extraction for %s",
                provider.upper(),
                document_name,
            )
            if not self.settings.ALLOW_OFFLINE_EXTRACTION_FALLBACK:
                raise ExtractionServiceError(
                    f"AI extraction is not configured (missing API key for provider '{provider}')."
                )

        try:
            data = self._extract_offline(doc_type, ocr_result)
        except Exception:
            # Last-resort safety net: the offline fallback itself must never
            # crash the request. If it does, degrade to an empty (all-null)
            # skeleton rather than surfacing an unhandled 500.
            logger.exception("Offline fallback extraction itself failed for %s", document_name)
            data = self._empty_skeleton(doc_type)
        return ExtractionOutcome(data=data, mode="offline_fallback")

    # ------------------------------------------------------------------
    # LLM-based extraction
    # ------------------------------------------------------------------
    def _extract_with_llm(self, doc_type: str, text: str, provider: str) -> dict[str, Any]:
        system_prompt = self._build_system_prompt(doc_type)
        user_text = text[:60000]

        if provider == "gemini":
            raw_text = self._call_gemini(system_prompt, user_text)
        elif provider == "anthropic":
            raw_text = self._call_anthropic(system_prompt, user_text)
        else:
            raise ExtractionServiceError(f"Unsupported LLM_PROVIDER: {provider}")

        return self._parse_json_response(raw_text)

    def _build_system_prompt(self, doc_type: str) -> str:
        instructions = _DOC_TYPE_INSTRUCTIONS[doc_type]
        return f"""You are a precise document-data-extraction engine for a financial
document intelligence platform. You will be given OCR/parsed text from a
{doc_type.replace('_', ' ')} document, with page boundaries marked as
"--- PAGE N ---".

Rules (follow strictly):
1. Extract ONLY values that are actually present in the text. If a value is
   not present or not legible, use null. NEVER invent, guess or infer a
   value that is not supported by the text.
2. Numbers must be plain JSON numbers (no currency symbols, no thousands
   separators). Parenthesised numbers like "(1,234.50)" mean -1234.50.
3. Dates: use ISO format YYYY-MM-DD when you can confidently determine it;
   otherwise return the raw text as shown.
4. For every top-level scalar field you extract, also provide the page
   number it was found on, and (where practical) a short verbatim
   "evidence_text" snippet (<=120 chars) copied from the source text that
   supports the value.
5. Output ONLY a single JSON object. No prose, no markdown code fences, no
   explanations.

{instructions}

Output JSON shape:
{{
  "fields": {{
     "<field_name>": {{"value": <string|number|null>, "page_number": <int|null>, "evidence_text": <string|null>}},
     ...
  }},
  "line_items": [ ... ],        // invoices only, omit/empty otherwise
  "statement_items": [ ... ],   // statements only, omit/empty for invoices
  "header": {{ "company_name": ..., "currency": ..., "period_current": ..., "period_comparative": ... }}
}}
"""

    def _call_gemini(self, system_prompt: str, user_text: str) -> str:
        import google.generativeai as genai

        try:
            genai.configure(api_key=self.settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(
                model_name=self.settings.GEMINI_MODEL,
                system_instruction=system_prompt,
                generation_config={
                    "max_output_tokens": self.settings.LLM_MAX_TOKENS,
                    "response_mime_type": "application/json",
                    "temperature": 0,
                },
            )
            response = model.generate_content(
                user_text,
                request_options={"timeout": self.settings.LLM_TIMEOUT_SECONDS},
            )
            # Accessing .text raises its own exception (not just returning
            # None/empty) if the response was blocked by safety filters or
            # has no valid candidate — must stay inside this try block so
            # that case is caught and converted into a controlled error
            # instead of an unhandled crash.
            text = (response.text or "").strip()
        except Exception as exc:
            raise ExtractionServiceError(f"Gemini call failed: {exc}") from exc

        if not text:
            raise ExtractionServiceError(
                "Gemini returned an empty response (possibly blocked by safety filters)."
            )
        return text

    def _call_anthropic(self, system_prompt: str, user_text: str) -> str:
        import anthropic

        client = anthropic.Anthropic(
            api_key=self.settings.ANTHROPIC_API_KEY,
            timeout=self.settings.LLM_TIMEOUT_SECONDS,
        )
        try:
            response = client.messages.create(
                model=self.settings.ANTHROPIC_MODEL,
                max_tokens=self.settings.LLM_MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_text}],
            )
        except Exception as exc:
            raise ExtractionServiceError(f"Anthropic call failed: {exc}") from exc

        raw_text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()
        return raw_text

    @staticmethod
    def _parse_json_response(raw_text: str) -> dict[str, Any]:
        candidate = raw_text.strip()
        match = _JSON_FENCE_RE.search(candidate)
        if match:
            candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Try to salvage by extracting the first {...} block
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(candidate[start : end + 1])
                except json.JSONDecodeError as exc:
                    raise ExtractionServiceError(
                        "LLM returned a response that could not be parsed as JSON."
                    ) from exc
            raise ExtractionServiceError(
                "LLM returned a response that could not be parsed as JSON."
            )

    # ------------------------------------------------------------------
    # Offline heuristic fallback (no API key / LLM unavailable)
    # ------------------------------------------------------------------
    def _extract_offline(self, doc_type: str, ocr_result: ExtractionText) -> dict[str, Any]:
        """
        Best-effort regex/label-matching extractor used only when the LLM
        path is unavailable. It intentionally only fills fields it can find
        with reasonable confidence and leaves everything else null, per the
        "do not invent values" requirement.
        """
        full_text = ocr_result.full_text
        fields: dict[str, dict[str, Any]] = {name: {"value": None, "page_number": None, "evidence_text": None}
                                              for name in REQUIRED_FIELDS[doc_type]}

        text_fields = {"invoice_number", "invoice_date", "vendor_name", "customer_name", "currency"}
        label_patterns = self._offline_label_patterns(doc_type)
        for field_name, patterns in label_patterns.items():
            for page in ocr_result.pages:
                for pattern in patterns:
                    m = re.search(pattern, page.text, re.IGNORECASE)
                    if m:
                        if field_name in text_fields:
                            value = m.group(1).strip()
                        else:
                            value = parse_bracketed_number(m.group(1))
                        if value is not None:
                            fields[field_name] = {
                                "value": value,
                                "page_number": page.page_number,
                                "evidence_text": m.group(0)[:120],
                            }
                            break
                if fields[field_name]["value"] is not None:
                    break

        result: dict[str, Any] = {"fields": fields, "header": {}, "line_items": [], "statement_items": []}
        return result

    @staticmethod
    def _offline_label_patterns(doc_type: str) -> dict[str, list[str]]:
        num = r"[:\s]*\(?[₹$€]?\s*([\d,]+\.?\d*)\)?"
        if doc_type == "invoice":
            return {
                "invoice_number": [r"invoice\s*(?:no|number|#)\s*[:\-]?\s*([A-Za-z0-9\-/]+)"],
                "invoice_date": [r"(?:invoice\s*date|date)\s*[:\-]?\s*([\d/\-\.]{6,10})"],
                "vendor_name": [r"(?:vendor|seller|from)\s*[:\-]\s*([A-Za-z0-9 &.,\-]{3,60})"],
                "customer_name": [r"(?:customer|bill\s*to|to)\s*[:\-]\s*([A-Za-z0-9 &.,\-]{3,60})"],
                "currency": [r"\b(USD|INR|EUR|GBP|Rs\.?|₹|\$)\b"],
                "subtotal": [rf"sub\s*total{num}"],
                "tax_amount": [rf"(?:tax|vat|gst)\s*(?:amount)?{num}"],
                "discount": [rf"discount{num}"],
                "total_amount": [rf"(?:total\s*amount(?:\s*due)?|grand\s*total){num}"],
            }
        if doc_type == "balance_sheet":
            return {
                "total_assets": [rf"total\s*assets{num}"],
                "total_liabilities": [rf"total\s*liabilit(?:y|ies){num}"],
                "total_equity": [rf"total\s*(?:equity|capital){num}"],
            }
        if doc_type == "profit_and_loss":
            return {
                "revenue": [rf"(?:total\s*)?revenue{num}", rf"total\s*income{num}"],
                "cost_of_sales": [rf"cost\s*of\s*(?:sales|goods\s*sold){num}"],
                "gross_profit": [rf"gross\s*profit{num}"],
                "operating_expenses": [rf"operating\s*expenses{num}"],
                "operating_profit": [rf"operating\s*profit{num}"],
                "tax": [rf"tax(?:ation)?{num}"],
                "net_profit": [rf"net\s*profit{num}"],
            }
        if doc_type == "cash_flow_statement":
            return {
                "operating_cash_flow": [rf"(?:net\s*cash\s*(?:flow\s*)?from\s*operating\s*activities){num}"],
                "investing_cash_flow": [rf"(?:net\s*cash\s*(?:flow\s*)?from\s*investing\s*activities){num}"],
                "financing_cash_flow": [rf"(?:net\s*cash\s*(?:flow\s*)?from\s*financing\s*activities){num}"],
                "opening_cash": [rf"(?:opening\s*cash(?:\s*(?:and|&)\s*cash\s*equivalents)?){num}"],
                "net_change_in_cash": [rf"net\s*(?:increase|change)\s*in\s*cash{num}"],
                "closing_cash": [rf"(?:closing\s*cash(?:\s*(?:and|&)\s*cash\s*equivalents)?){num}"],
            }
        return {}

    @staticmethod
    def _empty_skeleton(doc_type: str) -> dict[str, Any]:
        fields = {name: {"value": None, "page_number": None, "evidence_text": None}
                  for name in REQUIRED_FIELDS.get(doc_type, [])}
        return {"fields": fields, "header": {}, "line_items": [], "statement_items": []}