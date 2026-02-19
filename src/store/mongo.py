import os
import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo import MongoClient
from pymongo.collection import Collection

from src.core.config import MongoConfig
from src.core.crypto import encrypt_value, decrypt_value

_client: MongoClient | None = None
_db = None


def init_mongo(config: MongoConfig) -> None:
    global _client, _db
    uri = os.environ.get(config.uri_env, "mongodb://localhost:27017")
    _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    _db = _client[config.database]
    try:
        _db["jobs"].drop_index("url_1")
    except Exception:
        pass
    try:
        _db["jobs"].drop_index("dedupe_key_1")
    except Exception:
        pass
    _db["jobs"].create_index("url", unique=True)
    _db["jobs"].create_index([("active", 1), ("last_seen", -1)])
    try:
        _db["reviews"].drop_index("chat_id_1_job_url_1")
    except Exception:
        pass
    try:
        _db["votes"].drop_index("chat_id_1_job_url_1")
    except Exception:
        pass
    _db["reviews"].create_index([("chat_id", 1), ("job_id", 1)], unique=True)
    _db["users"].create_index("chat_id", unique=True)
    _db["queues"].create_index("chat_id", unique=True)
    _db["votes"].create_index([("chat_id", 1), ("job_id", 1)], unique=True)
    _db["feedback"].create_index("chat_id")
    _db["interviews"].create_index("job_id")
    _db["interviews"].create_index([("chat_id", 1), ("job_id", 1)], unique=True)
    _db["applications"].create_index([("chat_id", 1), ("job_id", 1)], unique=True)
    _db["applications"].create_index("chat_id")


def _col(name: str) -> Collection:
    return _db[name]


def save_user(chat_id: str, **fields) -> None:
    if "api_key" in fields and fields["api_key"]:
        fields["api_key"] = encrypt_value(fields["api_key"])
    now = datetime.now(timezone.utc).isoformat()
    update = {"$set": {**fields, "updated_at": now}, "$setOnInsert": {"created_at": now}}
    _col("users").update_one({"chat_id": chat_id}, update, upsert=True)


def get_user(chat_id: str) -> dict | None:
    doc = _col("users").find_one({"chat_id": chat_id}, {"_id": 0})
    if doc and doc.get("api_key"):
        doc["api_key"] = decrypt_value(doc["api_key"])
    return doc


def upsert_job(job: dict, chat_id: str = "") -> str:
    url = job.get("url", "")
    now = datetime.now(timezone.utc).isoformat()
    existing = _col("jobs").find_one({"url": url}) if url else None
    if existing:
        update: dict = {"$set": {"last_seen": now, "miss_count": 0, "active": True}}
        if chat_id:
            update["$addToSet"] = {"found_by": chat_id}
        _col("jobs").update_one({"url": url}, update)
        return str(existing["_id"])
    else:
        job["found_at"] = now
        job["last_seen"] = now
        job["miss_count"] = 0
        job["active"] = True
        job["found_by"] = [chat_id] if chat_id else []
        result = _col("jobs").insert_one(job)
        return str(result.inserted_id)


def save_jobs_batch(jobs: list[dict], chat_id: str = "") -> list[str]:
    return [upsert_job(job, chat_id=chat_id) for job in jobs]


def get_cached_review(chat_id: str, job_id: str) -> dict | None:
    return _col("reviews").find_one(
        {"chat_id": chat_id, "job_id": job_id},
        {"_id": 0},
    )


def save_review(chat_id: str, job_id: str, score: int, verdict: str, reason: str,
                 recruiter_message: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat()
    _col("reviews").update_one(
        {"chat_id": chat_id, "job_id": job_id},
        {"$set": {
            "score": score,
            "verdict": verdict,
            "reason": reason,
            "recruiter_message": recruiter_message,
            "reviewed_at": now,
        }},
        upsert=True,
    )


def save_search(chat_id: str, terms: list[str], countries: list[str], results_count: int) -> None:
    _col("searches").insert_one({
        "chat_id": chat_id,
        "terms": terms,
        "countries": countries,
        "results_count": results_count,
        "searched_at": datetime.now(timezone.utc).isoformat(),
    })


def get_job_by_url(url: str) -> dict | None:
    return _col("jobs").find_one({"url": url})


def get_job_by_id(job_id: str) -> dict | None:
    try:
        return _col("jobs").find_one({"_id": ObjectId(job_id)})
    except Exception:
        return None


def find_jobs_by_terms(chat_id: str, terms: list[str], max_age_hours: int = 48) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    regex_terms = [re.compile(re.escape(t), re.IGNORECASE) for t in terms]
    query = {
        "active": True,
        "last_seen": {"$gte": cutoff},
        "$or": [{"title": {"$regex": rt}} for rt in regex_terms]
             + [{"search_term": {"$in": terms}}],
    }
    return list(_col("jobs").find(query).sort("last_seen", -1))


def create_queue(chat_id: str, job_ids: list[str], terms: list[str], countries: list[str],
                  search_phase: int = 1, remote_only: bool = False) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _col("queues").update_one(
        {"chat_id": chat_id},
        {"$set": {
            "job_ids": job_ids,
            "current_index": 0,
            "terms": terms,
            "countries": countries,
            "created_at": now,
            "completed": False,
            "search_phase": search_phase,
            "is_searching": False,
            "remote_only": remote_only,
        }},
        upsert=True,
    )


def get_queue(chat_id: str) -> dict | None:
    return _col("queues").find_one({"chat_id": chat_id}, {"_id": 0})


def advance_queue(chat_id: str) -> None:
    _col("queues").update_one(
        {"chat_id": chat_id},
        {"$inc": {"current_index": 1}},
    )


def mark_queue_completed(chat_id: str) -> None:
    _col("queues").update_one(
        {"chat_id": chat_id},
        {"$set": {"completed": True}},
    )


def delete_queue(chat_id: str) -> None:
    _col("queues").delete_one({"chat_id": chat_id})


def set_search_phase(chat_id: str, phase: int) -> None:
    _col("queues").update_one(
        {"chat_id": chat_id},
        {"$set": {"search_phase": phase}},
    )


def set_searching(chat_id: str, value: bool) -> None:
    _col("queues").update_one(
        {"chat_id": chat_id},
        {"$set": {"is_searching": value}},
    )


def check_is_searching(chat_id: str) -> bool:
    q = _col("queues").find_one({"chat_id": chat_id}, {"is_searching": 1})
    return bool(q and q.get("is_searching"))


def extend_queue(chat_id: str, new_ids: list[str]) -> int:
    q = get_queue(chat_id)
    if not q:
        return 0
    existing = set(q.get("job_ids", []))
    unique_new = [i for i in new_ids if i not in existing]
    if unique_new:
        _col("queues").update_one(
            {"chat_id": chat_id},
            {"$push": {"job_ids": {"$each": unique_new}}},
        )
    return len(unique_new)


def has_active_queue(chat_id: str) -> bool:
    q = get_queue(chat_id)
    if not q or q.get("completed"):
        return False
    return q["current_index"] < len(q.get("job_ids", []))


def save_vote(chat_id: str, job_id: str, vote: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _col("votes").update_one(
        {"chat_id": chat_id, "job_id": job_id},
        {"$set": {"vote": vote, "voted_at": now}},
        upsert=True,
    )


def get_vote_summary(job_id: str) -> dict | None:
    votes = list(_col("votes").find({"job_id": job_id}, {"_id": 0, "vote": 1}))
    if not votes:
        return None
    up = sum(1 for v in votes if v.get("vote") == "up")
    down = sum(1 for v in votes if v.get("vote") == "down")
    return {"up": up, "down": down, "total": len(votes)}


def get_voted_job_ids(chat_id: str) -> set[str]:
    votes = _col("votes").find({"chat_id": chat_id}, {"job_id": 1})
    return {v["job_id"] for v in votes}


def save_feedback(chat_id: str, job_id: str, text: str) -> None:
    _col("feedback").insert_one({
        "chat_id": chat_id,
        "job_id": job_id,
        "text": text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def save_interview(chat_id: str, job_id: str, salary: str, currency: str,
                   stages: str, rating: int, experience: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _col("interviews").update_one(
        {"chat_id": chat_id, "job_id": job_id},
        {"$set": {
            "salary": salary,
            "currency": currency,
            "stages": stages,
            "rating": rating,
            "experience": experience,
            "created_at": now,
        }},
        upsert=True,
    )


def get_interview_summary(job_id: str) -> dict | None:
    interviews = list(_col("interviews").find({"job_id": job_id}, {"_id": 0}))
    if not interviews:
        return None
    ratings = [i["rating"] for i in interviews if i.get("rating")]
    avg_rating = sum(ratings) / len(ratings) if ratings else 0
    return {
        "count": len(interviews),
        "avg_rating": round(avg_rating, 1),
    }


def has_user_interview(chat_id: str, job_id: str) -> bool:
    return _col("interviews").find_one({"chat_id": chat_id, "job_id": job_id}) is not None


def save_application(chat_id: str, job_id: str, stage: str, result: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat()
    _col("applications").update_one(
        {"chat_id": chat_id, "job_id": job_id},
        {"$set": {"stage": stage, "result": result, "updated_at": now},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )


def get_application(chat_id: str, job_id: str) -> dict | None:
    return _col("applications").find_one(
        {"chat_id": chat_id, "job_id": job_id}, {"_id": 0},
    )


def delete_application(chat_id: str, job_id: str) -> None:
    _col("applications").delete_one({"chat_id": chat_id, "job_id": job_id})


def get_voted_jobs_with_details(chat_id: str, skip: int = 0, limit: int = 5) -> list[dict]:
    votes = list(
        _col("votes")
        .find({"chat_id": chat_id}, {"_id": 0})
        .sort("voted_at", -1)
        .skip(skip)
        .limit(limit)
    )
    results = []
    for v in votes:
        job_id = v.get("job_id", "")
        job = get_job_by_id(job_id)
        if not job:
            continue
        app = get_application(chat_id, job_id)
        results.append({
            "job_id": job_id,
            "vote": v.get("vote", ""),
            "voted_at": v.get("voted_at", ""),
            "title": job.get("title", "N/A"),
            "company": job.get("company", "N/A"),
            "url": job.get("url", ""),
            "stage": app.get("stage", "") if app else "",
            "result": app.get("result", "") if app else "",
        })
    return results


def count_user_votes(chat_id: str) -> int:
    return _col("votes").count_documents({"chat_id": chat_id})


def cleanup_old_jobs(max_age_days: int = 30) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    protected_ids = {
        str(doc["job_id"])
        for doc in _col("interviews").find({}, {"job_id": 1})
        if doc.get("job_id")
    }
    query = {"last_seen": {"$lt": cutoff}}
    old_jobs = list(_col("jobs").find(query, {"_id": 1}))
    to_delete = [j["_id"] for j in old_jobs if str(j["_id"]) not in protected_ids]
    if not to_delete:
        return 0
    delete_ids_str = [str(oid) for oid in to_delete]
    _col("jobs").delete_many({"_id": {"$in": to_delete}})
    _col("reviews").delete_many({"job_id": {"$in": delete_ids_str}})
    _col("votes").delete_many({"job_id": {"$in": delete_ids_str}})
    _col("feedback").delete_many({"job_id": {"$in": delete_ids_str}})
    return len(to_delete)
