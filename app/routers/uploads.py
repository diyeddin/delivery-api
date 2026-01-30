from fastapi import APIRouter, UploadFile, File, HTTPException, Query
import cloudinary
import cloudinary.uploader
from PIL import Image
import io

router = APIRouter(prefix="/upload", tags=["Uploads"])

# Folder Configuration
FOLDER_MAP = {
    "product": "mall_delivery/products",
    "store": "mall_delivery/stores",     # For logos/banners
    "avatar": "mall_delivery/avatars",   # For user profiles
    "misc": "mall_delivery/misc"
}

@router.post("/", status_code=200)
async def upload_image(
    file: UploadFile = File(...),
    type: str = Query("product", description="Type of image: product, store, avatar") # <--- NEW PARAMETER
):
    if file.content_type not in ["image/jpeg", "image/png", "image/webp"]:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, or WebP images allowed")

    # 1. Determine Target Folder
    target_folder = FOLDER_MAP.get(type, FOLDER_MAP["misc"])

    try:
        # 2. Process Image (Pillow)
        image = Image.open(file.file)

        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")

        # Resize Logic:
        # Avatars can be smaller, Banners larger. 
        if type == "avatar":
             image.thumbnail((500, 500))
        elif type == "store": 
             image.thumbnail((1200, 1200)) # Allow larger for banners
        else:
             image.thumbnail((1080, 1080)) # Default for products

        # 3. Save to Buffer
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80, optimize=True)
        buffer.seek(0)

        # 4. Upload with Dynamic Folder
        result = cloudinary.uploader.upload(
            buffer, 
            folder=target_folder, # <--- DYNAMIC FOLDER HERE
        )
        
        return {
            "url": result.get("secure_url"),
            "folder": target_folder
        }

    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Image processing failed")