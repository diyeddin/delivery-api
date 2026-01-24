"""Permission scope matrix for roles."""
from typing import Dict, List

SCOPE_MATRIX: Dict[str, List[str]] = {
    "customer": ["orders:create", "orders:read_own", "products:read"],
    "driver": ["orders:read", "orders:update_status", "location:update"],
    "store_owner": ["products:manage", "orders:read_store", "stores:manage"],
    "admin": ["*"]
}


def get_scopes_for_role(role: str) -> List[str]:
    return SCOPE_MATRIX.get(role, [])
