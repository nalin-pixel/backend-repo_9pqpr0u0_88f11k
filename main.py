import os
import hmac
import hashlib
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI(title="Premium Kids Fashion API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# Helper
# -----------------------------

def to_obj_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


# -----------------------------
# Schemas (request bodies)
# -----------------------------

class ProductCreate(BaseModel):
    title: str
    description: str
    price: float
    mrp: float
    gender: str
    category: str
    stock: int
    tags: List[str] = []
    image_urls: List[str] = []


class CartItem(BaseModel):
    user_id: str
    product_id: str
    quantity: int = Field(..., ge=1)


class WishlistItem(BaseModel):
    user_id: str
    product_id: str


class OrderCreate(BaseModel):
    user_id: str
    items: List[CartItem]
    total_price: float


# -----------------------------
# Health & Test
# -----------------------------

@app.get("/")
def read_root():
    return {"message": "Kids Fashion API running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected"
            response["database_url"] = "✅ Set"
            response["database_name"] = db.name
            response["collections"] = db.list_collection_names()
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    response["razorpay_key_id"] = "✅ Set" if os.getenv("RAZORPAY_KEY_ID") else "❌ Not Set"
    return response


# -----------------------------
# Products
# -----------------------------

@app.get("/api/products")
def list_products(
    gender: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    min_price: Optional[float] = Query(default=None),
    max_price: Optional[float] = Query(default=None),
    q: Optional[str] = Query(default=None),
):
    filt = {}
    if gender:
        filt["gender"] = gender
    if category:
        filt["category"] = category
    if min_price is not None or max_price is not None:
        price_query = {}
        if min_price is not None:
            price_query["$gte"] = float(min_price)
        if max_price is not None:
            price_query["$lte"] = float(max_price)
        filt["price"] = price_query
    if q:
        filt["title"] = {"$regex": q, "$options": "i"}
    items = list(db.products.find(filt).sort("created_at", -1))
    for it in items:
        it["id"] = str(it.pop("_id"))
    return {"items": items}


@app.get("/api/products/{product_id}")
def get_product(product_id: str):
    doc = db.products.find_one({"_id": to_obj_id(product_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    doc["id"] = str(doc.pop("_id"))
    return doc


@app.post("/api/products")
def create_product(payload: ProductCreate):
    pid = create_document("products", payload.model_dump())
    return {"id": pid}


@app.delete("/api/products/{product_id}")
def delete_product(product_id: str):
    res = db.products.delete_one({"_id": to_obj_id(product_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"ok": True}


# -----------------------------
# Wishlist
# -----------------------------

@app.get("/api/wishlist")
def get_wishlist(user_id: str):
    items = list(db.wishlist.find({"user_id": user_id}))
    for it in items:
        it["id"] = str(it.pop("_id"))
    return {"items": items}


@app.post("/api/wishlist")
def add_wishlist(item: WishlistItem):
    # prevent duplicates
    existing = db.wishlist.find_one({"user_id": item.user_id, "product_id": item.product_id})
    if existing:
        return {"id": str(existing["_id"])}
    wid = create_document("wishlist", item.model_dump())
    return {"id": wid}


@app.delete("/api/wishlist")
def remove_wishlist(user_id: str, product_id: str):
    res = db.wishlist.delete_one({"user_id": user_id, "product_id": product_id})
    return {"deleted": res.deleted_count > 0}


# -----------------------------
# Cart
# -----------------------------

@app.get("/api/cart")
def get_cart(user_id: str):
    items = list(db.cart.find({"user_id": user_id}))
    for it in items:
        it["id"] = str(it.pop("_id"))
    return {"items": items}


@app.post("/api/cart")
def add_to_cart(item: CartItem):
    existing = db.cart.find_one({"user_id": item.user_id, "product_id": item.product_id})
    if existing:
        db.cart.update_one({"_id": existing["_id"]}, {"$inc": {"quantity": item.quantity}})
        return {"id": str(existing["_id"]), "quantity": existing.get("quantity", 0) + item.quantity}
    cid = create_document("cart", item.model_dump())
    return {"id": cid}


@app.put("/api/cart")
def update_cart(item: CartItem):
    res = db.cart.update_one({"user_id": item.user_id, "product_id": item.product_id}, {"$set": {"quantity": item.quantity}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Cart item not found")
    return {"ok": True}


@app.delete("/api/cart")
def remove_from_cart(user_id: str, product_id: str):
    res = db.cart.delete_one({"user_id": user_id, "product_id": product_id})
    return {"deleted": res.deleted_count > 0}


# -----------------------------
# Orders + Razorpay
# -----------------------------

@app.post("/api/payment/create-order")
def create_payment_order(order: OrderCreate):
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")

    # amount in paise
    amount_paise = int(round(order.total_price * 100))

    # If keys present, create order via Razorpay API
    if key_id and key_secret:
        import requests
        payload = {"amount": amount_paise, "currency": "INR", "receipt": f"rcpt_{order.user_id}"}
        resp = requests.post(
            "https://api.razorpay.com/v1/orders",
            auth=(key_id, key_secret),
            json=payload,
            timeout=10,
        )
        if resp.status_code >= 300:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        data = resp.json()
        # save order minimally
        create_document(
            "orders",
            {
                "user_id": order.user_id,
                "items": [i.model_dump() for i in order.items],
                "total_price": order.total_price,
                "payment_status": "pending",
                "shipping_status": "pending",
                "razorpay_order_id": data.get("id"),
            },
        )
        return {"order": data, "key_id": key_id}

    # Fallback mock (for local without keys)
    mock_id = f"order_{ObjectId()}"
    create_document(
        "orders",
        {
            "user_id": order.user_id,
            "items": [i.model_dump() for i in order.items],
            "total_price": order.total_price,
            "payment_status": "pending",
            "shipping_status": "pending",
            "razorpay_order_id": mock_id,
        },
    )
    return {"order": {"id": mock_id, "amount": amount_paise, "currency": "INR"}, "key_id": "rzp_test_mock"}


class VerifyPayload(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@app.post("/api/payment/verify")
def verify_payment(body: VerifyPayload):
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    generated = hmac.new(
        (key_secret or "mock_secret").encode(),
        f"{body.razorpay_order_id}|{body.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    is_valid = generated == body.razorpay_signature if key_secret else True

    status = "paid" if is_valid else "failed"
    db.orders.update_one(
        {"razorpay_order_id": body.razorpay_order_id},
        {"$set": {"payment_status": status, "razorpay_payment_id": body.razorpay_payment_id}},
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return {"ok": True}


@app.post("/api/payment/webhook")
async def payment_webhook(payload: dict):
    # Minimal webhook handler: update order status when event received
    event = payload.get("event")
    entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    order_id = entity.get("order_id")
    status = entity.get("status")
    if order_id:
        db.orders.update_one(
            {"razorpay_order_id": order_id},
            {"$set": {"payment_status": status or "processing"}},
        )
    return {"received": True}


# -----------------------------
# Admin: list orders
# -----------------------------

@app.get("/api/orders")
def list_orders():
    items = list(db.orders.find().sort("created_at", -1))
    for it in items:
        it["id"] = str(it.pop("_id"))
    return {"items": items}


@app.put("/api/orders/{order_id}")
def update_order(order_id: str, payment_status: Optional[str] = None, shipping_status: Optional[str] = None):
    update = {}
    if payment_status:
        update["payment_status"] = payment_status
    if shipping_status:
        update["shipping_status"] = shipping_status
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = db.orders.update_one({"_id": to_obj_id(order_id)}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
