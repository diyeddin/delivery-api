"""
Permission scope matrix for roles.
Defines the granular permissions (scopes) assigned to each UserRole.
"""
from typing import Dict, List, Union
from app.db.models import UserRole

# SCOPE DEFINITIONS
# orders:read_all      -> View ALL orders in system (Admin only)
# orders:read          -> View available or assigned orders (Drivers)
# orders:read_own      -> View own history (Customer)
# orders:read_store    -> View orders for owned store (Store Owner)
# orders:create        -> Place new order
# orders:update_status -> Move order state (Driver: pick/deliver)
# orders:assign        -> Force assign driver (Admin)
# location:update      -> Update GPS coordinates (Driver)
# products:manage      -> Create/Edit products (Store Owner)
# stores:manage        -> Edit store details (Store Owner)
# users:manage         -> Change roles/ban users (Admin)

SCOPE_MATRIX: Dict[str, List[str]] = {
    UserRole.customer.value: [
        "orders:create", 
        "orders:read_own", 
        "products:read"
    ],
    UserRole.driver.value: [
        "orders:read",          # Limited read (assigned/available only)
        "orders:update_status", # Accept/PickUp/Deliver
        "location:update"       # High-freq GPS updates
    ],
    UserRole.store_owner.value: [
        "products:manage", 
        "orders:read_store", 
        "stores:manage"
    ],
    UserRole.admin.value: ["*"] # Wildcard grants all checks
}

def get_scopes_for_role(role: Union[str, UserRole]) -> List[str]:
    """
    Return the list of scopes for a given role.
    Handles both string inputs ("driver") and Enum inputs (UserRole.driver).
    """
    if isinstance(role, UserRole):
        role_key = role.value
    else:
        role_key = str(role)
        
    return SCOPE_MATRIX.get(role_key, [])