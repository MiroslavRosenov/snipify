from typing import Optional

from pydantic import BaseModel, Field


class CreateUrlRequest(BaseModel):
    url: str = Field()
    user_id: int


class CreateUrlResponse(BaseModel):
    status: str
    url_path: Optional[str]
