from PIL import Image
from io import BytesIO
import cloudinary.uploader
import pikepdf


MAX_IMAGE_SIZE = (1280, 1280)
IMAGE_QUALITY = 70


def compress_image(file) -> BytesIO:
    image = Image.open(file)
    image = image.convert("RGB")
    image.thumbnail(MAX_IMAGE_SIZE)

    buffer = BytesIO()
    image.save(buffer, format="JPEG", optimize=True, quality=IMAGE_QUALITY)
    buffer.seek(0)

    return buffer


async def upload_image(file, folder: str):
    compressed = compress_image(file)

    result = cloudinary.uploader.upload(
        compressed,
        folder=folder,
        resource_type="image",
        format="jpg"
    )

    return {
        "url": result["secure_url"],
        "public_id": result["public_id"]
    }




def compress_pdf(file) -> BytesIO:
    input_pdf = pikepdf.open(file)

    output = BytesIO()
    input_pdf.save(
        output,
        compress_streams=True
    )
    output.seek(0)

    return output


async def upload_pdf(file, folder: str):
    compressed = compress_pdf(file)

    result = cloudinary.uploader.upload(
        compressed,
        folder=folder,
        resource_type="raw",
        format="pdf"
    )

    return {
        "url": result["secure_url"],
        "public_id": result["public_id"]
    }

