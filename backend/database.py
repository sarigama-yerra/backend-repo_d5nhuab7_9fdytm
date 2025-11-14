import os
from datetime import datetime
from typing import Any, Dict, List
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "zenith_broking")

client = MongoClient(DATABASE_URL)
db = client[DATABASE_NAME]


def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    doc["_id"] = str(doc.get("_id"))
    return doc


def create_document(collection_name: str, data: Dict[str, Any]) -> str:
    data = {**data, "created_at": datetime.utcnow().isoformat()}
    result = db[collection_name].insert_one(data)
    return str(result.inserted_id)


def get_documents(collection_name: str, filter_dict: Dict[str, Any] | None = None, limit: int | None = None) -> List[Dict[str, Any]]:
    cursor = db[collection_name].find(filter_dict or {})
    if limit:
        cursor = cursor.limit(limit)
    return [serialize_doc(d) for d in cursor]


def get_document_by_id(collection: str, id_str: str) -> Dict[str, Any] | None:
    try:
        doc = db[collection].find_one({"_id": ObjectId(id_str)})
        return serialize_doc(doc) if doc else None
    except Exception:
        return None


def update_document_by_id(collection: str, id_str: str, data: Dict[str, Any]) -> bool:
    try:
        result = db[collection].update_one({"_id": ObjectId(id_str)}, {"$set": data})
        return result.modified_count > 0
    except Exception:
        return False


def increment_field_by_id(collection: str, id_str: str, inc: Dict[str, Any]) -> bool:
    try:
        result = db[collection].update_one({"_id": ObjectId(id_str)}, {"$inc": inc})
        return result.modified_count > 0
    except Exception:
        return False
