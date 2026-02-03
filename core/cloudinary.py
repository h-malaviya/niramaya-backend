import cloudinary
import os
from dotenv import load_dotenv
load_dotenv()

cloudinary.config(
    cloudinary_url=os.getenv("CLOUDINARY_URL"),
    secure=True
)
