"""PDF.co integration for Ira.

Provides :class:`PdfCoService`, an async wrapper around the PDF.co REST
API for:

* **HTML to PDF** -- convert HTML content to PDF (quotes, invoices).
* **Text extraction** -- extract text from complex/scanned PDFs.
* **Table extraction** -- extract tabular data from PDFs as CSV.

Constructed once at startup and injected via the service locator
(``ServiceKey.PDFCO``).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ira.config import PdfCoConfig, get_settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.pdf.co/v1"


class PdfCoError(Exception):
    """Raised when a PDF.co operation fails."""


class PdfCoService:
    """Async PDF.co client for PDF generation and extraction."""

    def __init__(self, config: PdfCoConfig | None = None) -> None:
        cfg = config or get_settings().pdfco
        self._api_key = cfg.api_key.get_secret_value()

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
        }

    # ── HTML to PDF ────────────────────────────────────────────────────

    async def html_to_pdf(
        self,
        html: str,
        *,
        name: str = "output.pdf",
        paper_size: str = "A4",
        orientation: str = "Portrait",
        margins: str = "10mm",
    ) -> bytes:
        """Convert HTML content to a PDF. Returns the PDF bytes."""
        if not self.available:
            raise PdfCoError("PDF.co API key not configured")

        payload = {
            "html": html,
            "name": name,
            "paperSize": paper_size,
            "orientation": orientation,
            "margins": margins,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            try:
                resp = await client.post(
                    f"{_BASE_URL}/pdf/convert/from/html",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("error"):
                    raise PdfCoError(f"PDF.co error: {data.get('message', 'unknown')}")

                pdf_url = data.get("url", "")
                if not pdf_url:
                    raise PdfCoError("No URL returned from PDF.co")

                pdf_resp = await client.get(pdf_url)
                pdf_resp.raise_for_status()
                return pdf_resp.content

            except httpx.HTTPError as exc:
                raise PdfCoError(f"PDF.co HTML-to-PDF failed: {exc}") from exc

    # ── text extraction ────────────────────────────────────────────────

    async def extract_text(
        self,
        file_bytes: bytes | None = None,
        *,
        file_url: str | None = None,
        pages: str = "",
    ) -> str:
        """Extract text from a PDF. Provide either file_bytes or file_url."""
        if not self.available:
            raise PdfCoError("PDF.co API key not configured")

        payload: dict[str, Any] = {"inline": True, "pages": pages}

        if file_url:
            payload["url"] = file_url
        elif file_bytes:
            upload_url = await self._upload_file(file_bytes, "document.pdf")
            payload["url"] = upload_url
        else:
            raise PdfCoError("Either file_bytes or file_url must be provided")

        async with httpx.AsyncClient(timeout=60) as client:
            try:
                resp = await client.post(
                    f"{_BASE_URL}/pdf/convert/to/text",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("error"):
                    raise PdfCoError(f"PDF.co error: {data.get('message', 'unknown')}")

                return data.get("body", "")

            except httpx.HTTPError as exc:
                raise PdfCoError(f"PDF.co text extraction failed: {exc}") from exc

    # ── table extraction ───────────────────────────────────────────────

    async def extract_tables_csv(
        self,
        file_bytes: bytes | None = None,
        *,
        file_url: str | None = None,
        pages: str = "",
    ) -> str:
        """Extract tables from a PDF as CSV text."""
        if not self.available:
            raise PdfCoError("PDF.co API key not configured")

        payload: dict[str, Any] = {"inline": True, "pages": pages}

        if file_url:
            payload["url"] = file_url
        elif file_bytes:
            upload_url = await self._upload_file(file_bytes, "document.pdf")
            payload["url"] = upload_url
        else:
            raise PdfCoError("Either file_bytes or file_url must be provided")

        async with httpx.AsyncClient(timeout=60) as client:
            try:
                resp = await client.post(
                    f"{_BASE_URL}/pdf/convert/to/csv",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("error"):
                    raise PdfCoError(f"PDF.co error: {data.get('message', 'unknown')}")

                return data.get("body", "")

            except httpx.HTTPError as exc:
                raise PdfCoError(f"PDF.co table extraction failed: {exc}") from exc

    # ── file upload helper ─────────────────────────────────────────────

    async def _upload_file(self, file_bytes: bytes, filename: str) -> str:
        """Upload a file to PDF.co's temporary storage and return the URL."""
        presign_payload = {"name": filename, "contenttype": "application/pdf"}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{_BASE_URL}/file/upload/get-presigned-url",
                params=presign_payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("error"):
                raise PdfCoError(f"PDF.co presign error: {data.get('message')}")

            presigned_url = data["presignedUrl"]
            result_url = data["url"]

            await client.put(
                presigned_url,
                content=file_bytes,
                headers={"Content-Type": "application/pdf"},
            )

        return result_url

    # ── health ─────────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        if not self.available:
            return {"status": "not_configured", "available": False}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_BASE_URL}/account/credit/balance",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "status": "connected",
                    "available": True,
                    "credits_remaining": data.get("remainingCredits", "?"),
                }
        except Exception as exc:
            return {"status": "error", "available": False, "error": str(exc)}
