import time
import asyncio

# In-memory database for temporary storage of captcha results
results_db = {}

async def init_db():
    print("[System] Results database initialized successfully (in-memory mode)")

async def save_result(task_id, task_type, data):
    # Store result; if data is a dict, store directly, otherwise construct a dict
    results_db[task_id] = data
    print(f"[System] Task {task_id} status updated: {data.get('value', 'Processing')}")

async def load_result(task_id):
    return results_db.get(task_id)

async def cleanup_old_results(days_old=7):
    # Simple cleanup logic
    now = time.time()
    to_delete = []
    for tid, res in results_db.items():
        if isinstance(res, dict) and now - res.get('createTime', now) > days_old * 86400:
            to_delete.append(tid)
    for tid in to_delete:
        del results_db[tid]
    return len(to_delete)