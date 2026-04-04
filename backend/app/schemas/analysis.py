from pydantic import BaseModel


class SummaryStats(BaseModel):
    count: int
    min: float
    max: float
    mean: float
    median: float
    std_dev: float


class CorrelationPoint(BaseModel):
    x: float
    y: float
    date: str
    target_name: str | None = None
    outlier: bool = False


class ConfidenceBandPoint(BaseModel):
    x: float
    y: float


class TrendLine(BaseModel):
    slope: float
    intercept: float
    r_squared: float
    pearson_r: float
    spearman_rho: float
    confidence_upper: list[ConfidenceBandPoint]
    confidence_lower: list[ConfidenceBandPoint]


class CorrelationResponse(BaseModel):
    points: list[CorrelationPoint]
    trend: TrendLine | None = None
    x_metric: str
    y_metric: str
    granularity: str
    x_stats: SummaryStats | None = None
    y_stats: SummaryStats | None = None


class HistogramBin(BaseModel):
    bin_start: float
    bin_end: float
    count: int


class DistributionResponse(BaseModel):
    bins: list[HistogramBin]
    stats: SummaryStats
    metric: str
    skewness: float


class BoxPlotGroup(BaseModel):
    group_name: str
    min: float
    q1: float
    median: float
    q3: float
    max: float
    outliers: list[float]
    count: int


class BoxPlotResponse(BaseModel):
    groups: list[BoxPlotGroup]
    metric: str
    group_by: str


class TimeSeriesPoint(BaseModel):
    date: str
    value: float
    target_name: str | None = None
    frame_count: int


class MovingAveragePoint(BaseModel):
    date: str
    value: float


class TimeSeriesResponse(BaseModel):
    points: list[TimeSeriesPoint]
    ma_7: list[MovingAveragePoint]
    ma_30: list[MovingAveragePoint]
    metric: str
    month_boundaries: list[str]


class MatrixCell(BaseModel):
    x_metric: str
    y_metric: str
    pearson_r: float | None
    n_points: int


class MatrixResponse(BaseModel):
    cells: list[MatrixCell]
    x_metrics: list[str]
    y_metrics: list[str]


class CompareGroupStats(BaseModel):
    name: str
    box: BoxPlotGroup
    stats: SummaryStats


class CompareResponse(BaseModel):
    group_a: CompareGroupStats
    group_b: CompareGroupStats
    metric: str
    mode: str
    verdict: str
