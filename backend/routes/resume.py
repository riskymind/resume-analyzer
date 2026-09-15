"""Resume upload, analysis, and history endpoints."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from database import get_connection
from models import AnalysisListItem, AnalysisRecord, AnalysisResult, Recommendations
from services.file_parser import FileParserError, extract_text
from services.gemini_client import GeminiClientError, analyze_resume

router = APIRouter()


@router.post("/analyze", response_model=AnalysisRecord)
async def analyze(
    resume: UploadFile = File(...),
    jd_text: str | None = Form(None),
    jd_file: UploadFile | None = File(None),
) -> AnalysisRecord:
    jd_text_provided = bool(jd_text and jd_text.strip())
    jd_file_provided = bool(jd_file is not None and jd_file.filename)

    if jd_text_provided == jd_file_provided:
        raise HTTPException(
            status_code=400,
            detail="Provide the job description as either pasted text or a file, not both or neither.",
        )

    try:
        resume_text = await extract_text(resume)
    except FileParserError as exc:
        raise HTTPException(status_code=400, detail=f"Resume file error: {exc}") from exc

    if jd_file_provided:
        try:
            jd_source_text = await extract_text(jd_file)
        except FileParserError as exc:
            raise HTTPException(status_code=400, detail=f"Job description file error: {exc}") from exc
        jd_source = jd_file.filename
    else:
        jd_source_text = jd_text.strip()
        jd_source = "pasted"

    try:
        result = analyze_resume(resume_text, jd_source_text)
    except GeminiClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    created_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO analyses (
                created_at, resume_filename, jd_source, resume_text, jd_text,
                score, score_label, recommendations_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                resume.filename,
                jd_source,
                resume_text,
                jd_source_text,
                result.score,
                result.score_label,
                result.recommendations.model_dump_json(),
            ),
        )
        analysis_id = cursor.lastrowid

    return AnalysisRecord(
        id=analysis_id,
        created_at=created_at,
        resume_filename=resume.filename,
        jd_source=jd_source,
        result=result,
    )


@router.get("/analyses", response_model=list[AnalysisListItem])
def list_analyses() -> list[AnalysisListItem]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, created_at, resume_filename, score, score_label "
            "FROM analyses ORDER BY created_at DESC"
        ).fetchall()

    return [AnalysisListItem(**dict(row)) for row in rows]


@router.get("/analyses/{analysis_id}", response_model=AnalysisRecord)
def get_analysis(analysis_id: int) -> AnalysisRecord:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found.")

    return AnalysisRecord(
        id=row["id"],
        created_at=row["created_at"],
        resume_filename=row["resume_filename"],
        jd_source=row["jd_source"],
        result=AnalysisResult(
            score=row["score"],
            score_label=row["score_label"],
            recommendations=Recommendations(**json.loads(row["recommendations_json"])),
        ),
    )
