from __future__ import annotations

import io
import zipfile
from pathlib import PurePosixPath

from fastapi import HTTPException, UploadFile, status

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def sanitize_upload_filename(filename: str | None) -> str:
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A .docx file is required.",
        )

    clean_name = PurePosixPath(filename.replace("\\", "/")).name.strip()
    if not clean_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid .docx filename is required.",
        )
    return clean_name


async def read_and_validate_docx_upload(
    file: UploadFile,
    *,
    max_upload_size_bytes: int,
) -> tuple[str, bytes]:
    filename = sanitize_upload_filename(file.filename)
    if not filename.lower().endswith(".docx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .docx files are allowed.",
        )

    content = await file.read(max_upload_size_bytes + 1)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty.",
        )

    if len(content) > max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds the {max_upload_size_bytes // (1024 * 1024)}MB limit.",
        )

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = set(archive.namelist())
            required_members = {"[Content_Types].xml", "word/document.xml"}
            if not required_members.issubset(members):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The uploaded file is not a valid .docx document.",
                )
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is not a valid .docx document.",
        ) from exc

    return filename, content
