from pydantic import BaseModel


class ExportFilterRow(BaseModel):
    date: str
    filter_name: str
    astrobin_filter_id: int | None = None
    frames: int
    exposure: float
    total_seconds: float
    gain: int | None = None
    sensor_temp: int | None = None
    fwhm: float | None = None
    sky_quality: float | None = None
    ambient_temp: float | None = None


class ExportEquipment(BaseModel):
    telescope: str | None
    camera: str | None


class ExportCalibration(BaseModel):
    darks: int
    flats: int
    bias: int


class ExportResponse(BaseModel):
    target_name: str
    catalog_id: str | None
    equipment: list[ExportEquipment]
    dates: list[str]
    rows: list[ExportFilterRow]
    calibration: ExportCalibration
    total_integration_seconds: float
    bortle: int | None = None
