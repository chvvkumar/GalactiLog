"""Filename-based target candidate detection: detect_filename_targets."""
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.worker.celery_app import celery_app
from app.worker.tasks_common import _sync_engine, _redis

logger = logging.getLogger(__name__)


@celery_app.task(name="detect_filename_targets")
def detect_filename_targets():
    """Scan uncategorized images (no OBJECT header) and extract targets from filenames."""
    import uuid
    from sqlalchemy import text as sa_text, select as sa_select, func as sa_func, or_
    from app.models.image import Image
    from app.models.filename_candidate import FilenameCandidate
    from app.services.filename_parser import extract_target_from_filename
    from app.services.filename_resolver import resolve_filename_candidate

    with Session(_sync_engine) as db:
        # Clear all pending candidates - re-detect from scratch with latest parser
        from sqlalchemy import delete as sa_delete
        db.execute(
            sa_delete(FilenameCandidate).where(FilenameCandidate.status == "pending")
        )
        db.commit()

        # Build noise set from known equipment/filter names in the DB
        db_noise: set[str] = set()
        for col in (Image.camera, Image.telescope, Image.filter_used):
            rows = db.execute(sa_select(col).where(col.isnot(None)).distinct()).all()
            for (val,) in rows:
                if val:
                    db_noise.add(val.lower())
                    # Also add individual words for multi-word names
                    # e.g. "ZWO ASI2600MM Pro" -> {"zwo asi2600mm pro", "zwo", "asi2600mm", "pro"}
                    for word in val.split():
                        db_noise.add(word.lower())

        # Find images with no resolved target and no OBJECT header
        unresolved_query = (
            sa_select(Image.id, Image.file_path)
            .where(
                Image.resolved_target_id.is_(None),
                Image.image_type == "LIGHT",
                or_(
                    ~Image.raw_headers.has_key("OBJECT"),
                    Image.raw_headers["OBJECT"].astext == "",
                    Image.raw_headers["OBJECT"].is_(None),
                ),
            )
        )
        unresolved = db.execute(unresolved_query).all()

        if not unresolved:
            return {"candidates_found": 0}

        # Get image_ids already tracked by accepted or dismissed candidates so
        # we don't re-process them. Dismissed means the user explicitly
        # rejected the suggestion - a rescan must not resurrect it.
        existing_candidates = db.execute(
            sa_select(FilenameCandidate.image_ids)
            .where(FilenameCandidate.status.in_(["accepted", "dismissed"]))
        ).all()
        tracked_image_ids = set()
        for row in existing_candidates:
            if row[0]:
                tracked_image_ids.update(row[0])

        # Also collect extracted_names that are currently dismissed, so groups
        # keyed by directory (no extracted_name) or by new images that weren't
        # in the original dismissed image_ids still get skipped by name.
        dismissed_names_rows = db.execute(
            sa_select(FilenameCandidate.extracted_name)
            .where(FilenameCandidate.status == "dismissed")
        ).all()
        dismissed_names = {row[0] for row in dismissed_names_rows if row[0]}

        # Group by extracted name
        groups: dict[str | None, list[tuple]] = {}  # key -> [(image_id, file_path)]
        for image_id, file_path in unresolved:
            if image_id in tracked_image_ids:
                continue
            extracted = extract_target_from_filename(Path(file_path), db_noise=db_noise)
            # For "no guess" files, key by parent directory
            key = extracted if extracted else f"__dir__:{Path(file_path).parent}"
            groups.setdefault(key, []).append((image_id, file_path))

        candidates_found = 0
        for key, files in groups.items():
            image_ids = [f[0] for f in files]
            file_paths = [f[1] for f in files]

            is_no_guess = key.startswith("__dir__:")
            extracted_name = None if is_no_guess else key

            if extracted_name and extracted_name in dismissed_names:
                continue

            # Check if a pending candidate with this extracted_name already exists
            if extracted_name:
                existing = db.execute(
                    sa_select(FilenameCandidate)
                    .where(
                        FilenameCandidate.extracted_name == extracted_name,
                        FilenameCandidate.status == "pending",
                    )
                ).scalar_one_or_none()
                if existing:
                    # Append to existing candidate
                    existing.image_ids = list(set(list(existing.image_ids or []) + image_ids))
                    existing.file_paths = list(set(list(existing.file_paths or []) + file_paths))
                    existing.file_count = len(existing.image_ids)
                    continue

            # Resolve the extracted name
            if extracted_name:
                resolution = resolve_filename_candidate(extracted_name, db, redis=_redis)
            else:
                resolution = {
                    "method": "none",
                    "confidence": 0.0,
                    "suggested_target_id": None,
                    "suggested_target_name": None,
                }

            suggested_id = resolution.get("suggested_target_id")

            db.add(FilenameCandidate(
                extracted_name=extracted_name,
                suggested_target_id=uuid.UUID(suggested_id) if suggested_id else None,
                method=resolution["method"],
                confidence=resolution["confidence"],
                status="pending",
                file_count=len(files),
                file_paths=file_paths,
                image_ids=image_ids,
            ))
            candidates_found += 1

        db.commit()
        return {"candidates_found": candidates_found}
