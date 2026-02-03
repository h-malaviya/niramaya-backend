from fastapi import APIRouter, UploadFile, File, HTTPException
from services.file_upload_service import upload_image, upload_pdf

router = APIRouter()


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    content_type = file.content_type
    
    if not content_type:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    if content_type.startswith("image/"):
        return await upload_image(file.file, folder="images")

    if content_type == "application/pdf":
        return await upload_pdf(file.file, folder="pdfs")

    raise HTTPException(status_code=400, detail="Unsupported file type")
