from pydantic import BaseModel


class CorrelationPoint(BaseModel):
    x: float
    y: float
    date: str
    target_name: str | None = None


class TrendLine(BaseModel):
    slope: float
    intercept: float
    r_squared: float


class CorrelationResponse(BaseModel):
    points: list[CorrelationPoint]
    trend: TrendLine | None = None
    x_metric: str
    y_metric: str
    granularity: str
