"""
Redis cache utilities for common caching patterns.
"""
from core.redis import redis_client
import json
from typing import Optional, List, Callable, Any
from functools import wraps

class CacheManager:
    """Helper class for common caching operations."""
    
    @staticmethod
    async def get_or_set(
        key: str,
        fetch_func: Callable,
        ttl: int,
        *args,
        **kwargs
    ) -> Any:
        """
        Get value from cache, or fetch and cache it if not present.
        
        Args:
            key: Redis cache key
            fetch_func: Async function to call if cache miss
            ttl: Time to live in seconds
            *args, **kwargs: Arguments to pass to fetch_func
        """
        try:
            cached = await redis_client.get(key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
        
        # Cache miss - fetch data
        data = await fetch_func(*args, **kwargs)
        
        # Cache the result
        try:
            await redis_client.setex(key, ttl, json.dumps(data))
        except Exception:
            pass
        
        return data
    
    @staticmethod
    async def invalidate_pattern(pattern: str):
        """
        Invalidate all keys matching a pattern.
        Note: Use sparingly as SCAN can be expensive.
        """
        try:
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)
                if keys:
                    await redis_client.delete(*keys)
                if cursor == 0:
                    break
        except Exception:
            pass
    
    @staticmethod
    async def delete_keys(*keys: str):
        """Delete multiple cache keys."""
        try:
            if keys:
                await redis_client.delete(*keys)
        except Exception:
            pass


def cache_result(key_prefix: str, ttl: int = 300):
    """
    Decorator to cache async function results.
    
    Usage:
        @cache_result("user", ttl=600)
        async def get_user(user_id: int):
            ...
    
    This will cache with key: "user:{user_id}"
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key from function arguments
            # Assuming first arg after self is the ID
            if args and len(args) > 1:
                cache_key = f"{key_prefix}:{args[1]}"
            else:
                # Fallback to stringified args
                cache_key = f"{key_prefix}:{str(args)}:{str(kwargs)}"
            
            # Try cache first
            try:
                cached = await redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception:
                pass
            
            # Cache miss - call function
            result = await func(*args, **kwargs)
            
            # Cache the result
            try:
                await redis_client.setex(cache_key, ttl, json.dumps(result))
            except Exception:
                pass
            
            return result
        
        return wrapper
    return decorator


class ListCache:
    """Helper for caching lists of IDs with individual item caching."""
    
    @staticmethod
    async def get_list(
        list_key: str,
        item_key_prefix: str,
        fetch_list_func: Callable,
        fetch_item_func: Callable,
        list_ttl: int,
        item_ttl: int,
    ) -> List[Any]:
        """
        Get a list of items with two-level caching:
        1. Cache list of IDs
        2. Cache individual items
        
        Args:
            list_key: Redis key for the list of IDs
            item_key_prefix: Prefix for individual item keys
            fetch_list_func: Async function to fetch all items from DB
            fetch_item_func: Async function to fetch single item by ID
            list_ttl: TTL for the list cache
            item_ttl: TTL for individual items
        """
        # Try to get list of IDs from cache
        try:
            cached_ids = await redis_client.get(list_key)
            if cached_ids:
                ids = json.loads(cached_ids)
                items = []
                
                # Fetch each item (will use cache if available)
                for item_id in ids:
                    try:
                        item = await fetch_item_func(item_id)
                        items.append(item)
                    except Exception:
                        # If any item fails, invalidate list cache and refetch
                        await redis_client.delete(list_key)
                        break
                else:
                    # All items fetched successfully
                    return items
        except Exception:
            pass
        
        # Cache miss or partial failure - fetch all from database
        items = await fetch_list_func()
        
        # Cache the list of IDs
        try:
            ids = [getattr(item, 'id', None) for item in items if hasattr(item, 'id')]
            await redis_client.setex(list_key, list_ttl, json.dumps(ids))
        except Exception:
            pass
        
        return items
    
    @staticmethod
    async def invalidate_list(*keys: str):
        """Invalidate list cache keys."""
        try:
            if keys:
                await redis_client.delete(*keys)
        except Exception:
            pass


# Example usage patterns:

# Pattern 1: Simple key-value caching
async def get_user_cached(user_id: int):
    cache_key = f"user:{user_id}"
    
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    
    # Fetch from database
    user = await fetch_user_from_db(user_id)
    
    # Cache it
    try:
        await redis_client.setex(cache_key, 600, json.dumps(user))
    except Exception:
        pass
    
    return user


# Pattern 2: List caching with individual items
async def get_all_products_cached():
    list_key = "products:all"
    
    try:
        cached_ids = await redis_client.get(list_key)
        if cached_ids:
            product_ids = json.loads(cached_ids)
            products = []
            for pid in product_ids:
                product = await get_product_cached(pid)
                products.append(product)
            return products
    except Exception:
        pass
    
    # Fetch from database
    products = await fetch_all_products_from_db()
    
    # Cache list and individual items
    try:
        product_ids = [p.id for p in products]
        await redis_client.setex(list_key, 300, json.dumps(product_ids))
        
        for product in products:
            await cache_product(product)
    except Exception:
        pass
    
    return products


# Pattern 3: Cache invalidation
async def invalidate_product_caches(product_id: int, store_id: int = None):
    keys = [
        f"product:{product_id}",
        "products:all",
    ]
    
    if store_id:
        keys.append(f"products:store:{store_id}")
    
    try:
        await redis_client.delete(*keys)
    except Exception:
        pass