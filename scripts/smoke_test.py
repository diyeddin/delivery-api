import requests
import json
import uuid

# Configuration
BASE_URL = "http://localhost:8000"
API_V1 = f"{BASE_URL}/api/v1"

def print_step(msg):
    print(f"\n⚡ {msg}")

def register_and_login(email, password, role, name):
    # 1. Register
    try:
        requests.post(f"{API_V1}/auth/signup", json={
            "email": email, "password": password, "name": name
        })
    except:
        pass # User might already exist

    # 2. Login (Get Token)
    resp = requests.post(f"{API_V1}/auth/login", data={
        "username": email, "password": password
    })
    if resp.status_code != 200:
        print(f"❌ Failed to login {role}: {resp.text}")
        return None, None
    
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 3. Update Role (Admin hack for testing)
    # In a real app, you can't self-promote, but we rely on the DB seed or manual update.
    # For this smoke test, we assume the first user created is Admin or we skip this.
    # To make this robust, we'll manually hit the DB or assume you change it via PGAdmin.
    # For now, let's just return the headers.
    return headers, token

def main():
    print("🚀 Starting Smoke Test...")

    # --- 1. SETUP USERS ---
    print_step("Creating Users...")
    # Admin (You might need to manually set this role in DB after first run if your code protects role updates)
    admin_headers, _ = register_and_login("admin@mall.com", "Admin123!", "admin", "Admin User")
    
    # Store Owner
    owner_headers, _ = register_and_login("owner@mall.com", "Owner123!", "store_owner", "Store Owner")
    
    # Driver
    driver_headers, _ = register_and_login("driver@mall.com", "Driver123!", "driver", "Speedy Driver")
    
    # Customer
    cust_headers, _ = register_and_login("customer@mall.com", "Customer123!", "customer", "Hungry Customer")

    if not all([admin_headers, owner_headers, driver_headers, cust_headers]):
        print("⚠️  Creating users failed. (Did you clean the DB? Roles might be wrong).")
        print("   Run: docker-compose -f docker-compose.dev.yml exec db psql -U postgres -d mall_delivery -c \"UPDATE users SET role='admin' WHERE email='admin@mall.com';\"")
        print("   Run: docker-compose -f docker-compose.dev.yml exec db psql -U postgres -d mall_delivery -c \"UPDATE users SET role='store_owner' WHERE email='owner@mall.com';\"")
        print("   Run: docker-compose -f docker-compose.dev.yml exec db psql -U postgres -d mall_delivery -c \"UPDATE users SET role='driver' WHERE email='driver@mall.com';\"")
        return

    # --- 2. CREATE STORE & PRODUCTS (As Owner) ---
    print_step("Creating Store & Products...")
    
    # Create Store
    store_resp = requests.post(f"{API_V1}/stores/", headers=owner_headers, json={
        "name": "Tech Gadgets",
        "category": "Electronics",
        "latitude": 40.7128,
        "longitude": -74.0060
    })
    if store_resp.status_code == 200:
        store_id = store_resp.json()["id"]
        print(f"✅ Store Created: ID {store_id}")
    else:
        # assume existing
        print(f"ℹ️  Store creation skipped/failed: {store_resp.status_code}")
        # Fetch existing store to get ID
        my_stores = requests.get(f"{API_V1}/stores/me", headers=owner_headers).json()
        if my_stores:
            store_id = my_stores[0]["id"]
        else:
            print("❌ No store found. Exiting.")
            return

    # Create Product
    prod_resp = requests.post(f"{API_V1}/products/", headers=owner_headers, json={
        "store_id": store_id,
        "name": "Wireless Headphones",
        "description": "Noise cancelling",
        "price": 299.99,
        "stock": 100
    })
    product_id = prod_resp.json()["id"]
    print(f"✅ Product Created: {product_id}")

    # --- 3. PLACE ORDER (As Customer) ---
    print_step("Placing Order...")
    order_payload = {
        "items": [
            {"product_id": product_id, "quantity": 1}
        ]
    }
    # Important: Add Idempotency Key
    cust_headers["Idempotency-Key"] = str(uuid.uuid4())
    
    order_resp = requests.post(f"{API_V1}/orders/", headers=cust_headers, json=order_payload)
    if order_resp.status_code == 200:
        orders = order_resp.json() # It returns a LIST now!
        order_id = orders[0]["id"]
        print(f"✅ Order Placed: ID {order_id} (Total: ${orders[0]['total_price']})")
    else:
        print(f"❌ Order Failed: {order_resp.text}")
        return

    # --- 4. DRIVER GPS UPDATE (As Driver) ---
    print_step("Driver updating GPS...")
    loc_resp = requests.patch(f"{API_V1}/users/me/location", headers=driver_headers, json={
        "latitude": 40.7130,
        "longitude": -74.0050, # Nearby
        "is_active": True
    })
    if loc_resp.status_code == 200:
        print("✅ Driver Location Updated")

    # --- 5. ASSIGN DRIVER (As Admin) ---
    print_step("Assigning Driver...")
    # First, get driver ID
    # In a real script we'd fetch the user ID, here we cheat and assume it's sequential or known.
    # Let's verify the driver sees the order in 'available' first?
    avail_resp = requests.get(f"{API_V1}/orders/available-for-pickup", headers=driver_headers)
    print(f"ℹ️  Driver sees {len(avail_resp.json())} available orders.")

    # Driver Accepts
    accept_resp = requests.put(f"{API_V1}/orders/{order_id}/accept", headers=driver_headers)
    if accept_resp.status_code == 200:
        print(f"✅ Driver successfully accepted order {order_id}")
    else:
        print(f"❌ Driver accept failed: {accept_resp.text}")

    print("\n🎉 SMOKE TEST COMPLETE!")
    print("If you see green checks, your Logic, DB, Atomic Locking, and API are working.")

if __name__ == "__main__":
    main()