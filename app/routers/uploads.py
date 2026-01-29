from fastapi import APIRouter, UploadFile, File, HTTPException
import cloudinary
import cloudinary.uploader
from PIL import Image
import io

router = APIRouter(prefix="/upload", tags=["Uploads"])

@router.post("/", status_code=200)
async def upload_image(file: UploadFile = File(...)):
    if file.content_type not in ["image/jpeg", "image/png", "image/webp"]:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, or WebP images allowed")

    try:
        # 1. Open the image using Pillow
        # We read the file bytes directly
        image = Image.open(file.file)

        # 2. (Optional) Convert to RGB if it's PNG/RGBA to avoid errors saving as JPEG
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")

        # 3. Resize Logic (Max Width 1080px)
        # We use 'thumbnail' which preserves aspect ratio
        max_size = (1080, 1080)
        image.thumbnail(max_size)

        # 4. Save the processed image to a memory buffer (Ram)
        # This acts like a "fake file" so we don't have to save to disk
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80, optimize=True)
        buffer.seek(0) # Rewind the buffer to the beginning so Cloudinary can read it

        # 5. Upload the BUFFER to Cloudinary
        result = cloudinary.uploader.upload(
            buffer, 
            folder="mall_delivery/products",
            # public_id=file.filename.split('.')[0] # Optional: Keep original name
        )
        
        return {"url": result.get("secure_url")}

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Image processing failed")