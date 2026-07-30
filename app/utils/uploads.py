"""Safe handling of uploaded payment receipts (PDF / JPG / PNG, max 10 MB)."""
import os
import uuid

from fastapi import HTTPException, UploadFile

from app.config import settings

ALLOWED = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}
# magic bytes — don't trust the browser's content-type alone
SIGNATURES = {
    ".pdf": [b"%PDF"],
    ".jpg": [b"\xff\xd8\xff"],
    ".png": [b"\x89PNG"],
}


def receipts_dir() -> str:
    d = os.path.join(settings.UPLOADS_DIR, "receipts")
    os.makedirs(d, exist_ok=True)
    return d


async def save_receipt_upload(file: UploadFile) -> dict:
    """Validate and store an uploaded receipt. Returns file metadata."""
    ctype = (file.content_type or "").lower()
    ext = ALLOWED.get(ctype)
    if not ext:
        # fall back to the filename extension for browsers that send
        # application/octet-stream
        name_ext = os.path.splitext(file.filename or "")[1].lower()
        ext = {".pdf": ".pdf", ".jpg": ".jpg", ".jpeg": ".jpg",
               ".png": ".png"}.get(name_ext)
    if not ext:
        raise HTTPException(
            status_code=400,
            detail="Only PDF, JPG or PNG receipts are allowed.")

    max_bytes = settings.MAX_RECEIPT_MB * 1024 * 1024
    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Receipt is too large (max {settings.MAX_RECEIPT_MB} MB).")
    if len(data) < 16:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if not any(data.startswith(sig) for sig in SIGNATURES[ext]):
        raise HTTPException(
            status_code=400,
            detail="The file content does not match a PDF/JPG/PNG receipt.")

    filename = uuid.uuid4().hex + ext
    path = os.path.join(receipts_dir(), filename)
    with open(path, "wb") as f:
        f.write(data)
    return {
        "file_path": path,
        "original_name": (file.filename or filename)[:200],
        "content_type": ctype or "application/octet-stream",
        "size_bytes": len(data),
    }
