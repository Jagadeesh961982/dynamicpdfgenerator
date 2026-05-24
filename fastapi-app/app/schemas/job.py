from datetime import datetime
from typing import Any

from pydantic import BaseModel


class JobOut(BaseModel):
    id: str
    status: str
    error_message: str | None
    input_filename: str | None
    output_pdf_path: str | None
    result_json: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}
