"""Typed Reducto API client (upload → parse → extract) with retries."""

import logging
from typing import Any

import httpx
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class ReductoSettings(BaseSettings):
    api_key: str = ""
    base_url: str = "https://platform.reducto.ai"

    model_config = {"env_prefix": "REDUCTO_", "extra": "ignore"}


class UploadResponse(BaseModel):
    file_id: str
    presigned_url: str | None = None


class ParseResponse(BaseModel):
    job_id: str
    duration: float | None = None
    result: dict[str, Any] | None = None


class ExtractResponse(BaseModel):
    job_id: str | None = None
    usage: dict[str, Any]
    result: list[dict[str, Any]] | dict[str, Any]


def _should_retry(exc: BaseException) -> bool:
    """Retry on network/timeout/5xx; do not retry on 4xx."""
    if isinstance(exc, httpx.HTTPStatusError):
        return not (400 <= exc.response.status_code < 500)
    return True


def _retry():
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_should_retry),
        reraise=True,
    )


class ReductoClient:
    """Client for Reducto parse and extract. Uses upload then parse; extract uses same input ref."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        settings = ReductoSettings()
        self.api_key = (api_key or settings.api_key or "").strip()
        self.base_url = (base_url or settings.base_url).rstrip("/")
        if not self.api_key:
            raise ValueError("REDUCTO_API_KEY not set")

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @_retry()
    def _upload_bytes(self, pdf_bytes: bytes) -> UploadResponse:
        with httpx.Client(timeout=120.0) as client:
            r = client.post(
                f"{self.base_url}/upload",
                headers=self._headers(),
                files={"file": ("document.pdf", pdf_bytes, "application/pdf")},
            )
            r.raise_for_status()
            return UploadResponse.model_validate(r.json())

    @_retry()
    def parse_pdf_bytes(self, pdf_bytes: bytes) -> dict[str, Any]:
        """Upload PDF and run parse. Returns full parse response as dict with _input_ref set."""
        upload = self._upload_bytes(pdf_bytes)
        # API accepts UploadResponse or reducto:// URL
        input_ref = {"file_id": upload.file_id}
        with httpx.Client(timeout=300.0) as client:
            r = client.post(
                f"{self.base_url}/parse",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"input": input_ref},
            )
            r.raise_for_status()
            data = r.json()
        data["_input_ref"] = input_ref
        logger.info("Parse job_id=%s", data.get("job_id"))
        return data

    EXTRACT_INSTRUCTIONS = (
        "Extract ONLY the fields in the schema. If a value is not explicitly present, use null. Do not guess. "
        "If there are conflicting values, set the field to null and add an entry to issues with the conflicting candidates. "
        "For every non-null field, provide evidence in an evidence array with: field_path, page number, and the exact quoted text snippet."
    )

    @_retry()
    def extract_from_parse(
        self, parse_response: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Run extract using input ref from parse response and given JSON schema. Returns full extract response."""
        raw_ref = (
            parse_response.get("_input_ref")
            or parse_response.get("input")
            or parse_response.get("document_url")
            or parse_response.get("file_url")
        )
        if raw_ref is None:
            raise ValueError(
                "No input reference found for extract (need _input_ref, input, document_url, or file_url)"
            )
        if isinstance(raw_ref, dict) and "file_id" in raw_ref:
            input_ref = f"reducto://{raw_ref['file_id']}"
        elif isinstance(raw_ref, str):
            input_ref = raw_ref
        else:
            raise ValueError(
                f"Input reference must be a string or dict with file_id, got {type(raw_ref).__name__}"
            )
        payload = {
            "input": input_ref,
            "instructions": {
                "schema": schema,
                "system_prompt": self.EXTRACT_INSTRUCTIONS,
            },
        }
        logger.debug("extract input_ref=%s", input_ref)
        logger.debug("extract schema title=%s", schema.get("title"))
        logger.debug("extract payload keys=%s", list(payload.keys()))
        with httpx.Client(timeout=300.0) as client:
            r = client.post(
                f"{self.base_url}/extract",
                headers={**self._headers(), "Content-Type": "application/json"},
                json=payload,
            )
            if r.status_code == 422:
                try:
                    detail = r.json()
                except Exception:
                    detail = r.text
                raise ValueError(f"Reducto extract 422 Validation Error: {detail}")
            r.raise_for_status()
            data = r.json()
        logger.info("Extract job_id=%s", data.get("job_id"))
        return data
