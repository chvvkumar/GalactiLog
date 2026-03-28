import uuid
from datetime import datetime

from pydantic import BaseModel

from .target import TargetRead


class ImageBase(BaseModel):
    file_path: str
    file_name: str
    capture_date: datetime | None = None
    exposure_time: float | None = None
    filter_used: str | None = None
    sensor_temp: float | None = None
    camera_gain: int | None = None
    image_type: str | None = None
    telescope: str | None = None
    camera: str | None = None
    median_hfr: float | None = None
    eccentricity: float | None = None


class ImageRead(ImageBase):
    id: uuid.UUID
    thumbnail_path: str | None = None
    resolved_target_id: uuid.UUID | None = None
    raw_headers: dict | None = None

    model_config = {"from_attributes": True}


class ImageDetail(ImageRead):
    target: TargetRead | None = None


class ImageListResponse(BaseModel):
    items: list[ImageRead]
    total: int
    page: int
    page_size: int


class ImageFilterParams(BaseModel):
    target_name: str | None = None
    filter_used: str | None = None
    image_type: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    min_exposure: float | None = None
    max_exposure: float | None = None
    header_key: str | None = None
    header_value: str | None = None
    page: int = 1
    page_size: int = 50
