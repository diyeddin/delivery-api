import cloudinary.uploader
import re
from app.core.logging import get_logger

logger = get_logger(__name__)

def get_public_id_from_url(url: str) -> str:
    """
    Extracts the public ID from a Cloudinary URL.
    Input:  https://.../upload/v1234/mall_delivery/stores/banner.jpg
    Output: mall_delivery/stores/banner
    """
    try:
        # Regex finds everything after '/upload/' (ignoring version v123) and before extension
        match = re.search(r'/upload/(?:v\d+/)?(.+)\.[^.]+$', url)
        return match.group(1) if match else None
    except Exception:
        return None

def delete_cloudinary_image(url: str):
    """
    Deletes an image from Cloudinary. 
    Intended to be run as a BackgroundTask.
    """
    if not url or "cloudinary" not in url:
        return

    public_id = get_public_id_from_url(url)
    if public_id:
        try:
            cloudinary.uploader.destroy(public_id)
            logger.info(f"🗑️ Cleaned up old image: {public_id}")
        except Exception as e:
            logger.error(f"⚠️ Failed to delete image {public_id}: {e}")