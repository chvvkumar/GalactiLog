from app.schemas.target import (
    SessionOverview,
    FilterDetail,
    SessionInsight,
    FrameRecord,
    TargetDetailResponse,
    SessionDetailResponse,
)


def test_session_overview_minimal():
    s = SessionOverview(
        session_date="2026-03-20",
        integration_seconds=3600.0,
        frame_count=12,
        median_hfr=None,
        median_eccentricity=None,
        filters_used=["Ha"],
        camera=None,
        telescope=None,
    )
    assert s.session_date == "2026-03-20"
    assert s.frame_count == 12


def test_filter_detail():
    fd = FilterDetail(
        filter_name="Ha",
        frame_count=40,
        integration_seconds=12000.0,
        median_hfr=2.1,
        median_eccentricity=0.38,
        exposure_time=300.0,
    )
    assert fd.filter_name == "Ha"
    assert fd.integration_seconds == 12000.0


def test_session_insight():
    si = SessionInsight(level="good", message="Best HFR session")
    assert si.level == "good"


def test_frame_record():
    fr = FrameRecord(
        timestamp="2026-03-20T21:14:00",
        filter_used="Ha",
        exposure_time=300.0,
        median_hfr=2.1,
        eccentricity=0.38,
        sensor_temp=-10.0,
        gain=100,
        file_name="Light_Ha_001.fits",
    )
    assert fr.file_name == "Light_Ha_001.fits"


def test_target_detail_response():
    td = TargetDetailResponse(
        target_id="abc-123",
        primary_name="M 42",
        aliases=["Orion Nebula"],
        object_type="Nebula",
        ra=83.822,
        dec=-5.391,
        total_integration_seconds=170000.0,
        total_frames=1847,
        avg_hfr=2.31,
        avg_eccentricity=0.42,
        filters_used=["Ha", "OIII"],
        equipment=["ZWO ASI2600MM", "Esprit 150"],
        first_session_date="2024-10-12",
        last_session_date="2026-03-20",
        session_count=12,
        sessions=[],
    )
    assert td.primary_name == "M 42"
    assert td.session_count == 12


def test_session_detail_response_new_fields():
    sd = SessionDetailResponse(
        target_name="M 42",
        session_date="2026-03-20",
        thumbnail_url=None,
        frame_count=156,
        integration_seconds=15120.0,
        median_hfr=2.1,
        median_eccentricity=0.38,
        filters_used={"Ha": 80, "OIII": 76},
        equipment={"camera": "ZWO ASI2600MM", "telescope": "Esprit 150"},
        raw_reference_header=None,
        min_hfr=1.8,
        max_hfr=3.2,
        min_eccentricity=0.31,
        max_eccentricity=0.52,
        sensor_temp=-10.0,
        sensor_temp_min=-10.0,
        sensor_temp_max=-10.0,
        gain=100,
        exposure_time=300.0,
        first_frame_time="2026-03-20T21:14:00",
        last_frame_time="2026-03-21T04:32:00",
        filter_details=[],
        insights=[],
        frames=[],
    )
    assert sd.min_hfr == 1.8
    assert sd.gain == 100
