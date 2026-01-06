# intent_project/api/routes.py
import json
from typing import List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

# Core & Deps
from intent_project.core.config import settings
from intent_project.core import deps
from flowllm.core.schema import VectorNode

# Schemas
from intent_project.schemas.base import (
    ClassifyRequest, ClassifyResponse, IntentEnum,
    FeedbackRequest, MemoryMaintainRequest,
    CacheCheckRequest, CacheCheckResponse, SaveCacheRequest
)

# Services
from intent_project.services.cache_service import CacheService
from intent_project.services.llm_service import LLMService
from intent_project.services.memory_service import MemoryService

router = APIRouter()

# ================= Dependency Injection Helpers =================

def get_llm_service():
    return LLMService(client=deps.get_llm_client())

def get_memory_service():
    return MemoryService(vector_store=deps.get_vector_store())

def get_cache_service():
    return CacheService(
        vector_store=deps.get_vector_store(),
        llm_client=deps.get_llm_client()
    )

# ================= Classify Endpoints =================
@router.post("/classify", response_model=ClassifyResponse)
async def classify(
    req: ClassifyRequest, 
    request: Request,
    service: LLMService = Depends(get_llm_service)
):
    # 1. 尝试从 ReMe 获取上下文 (保持不变)
    memory_context = ""
    reme_app = getattr(request.app.state, "reme_app", None)
    
    if reme_app:
        search_query = req.history + "\nhuman: "+ req.query if req.history else req.query
        try:
            res = await reme_app.async_execute(
                name="retrieve_task_memory_simple",
                workspace_id=settings.UNIFIED_WORKSPACE_ID,
                query=search_query,
                top_k=5
            )
            if isinstance(res, dict) and "answer" in res:
                memory_context = res["answer"]
            elif hasattr(res, "result"):
                memory_context = str(res.result)
        except Exception as e:
            print(f"⚠️ ReMe Retrieve Skipped: {e}")

    # 2. 调用 Service 进行分类 (获取基础结果)
    # result 是 ClassifyResult (只包含 category, reasoning)
    result = await service.classify_intent(
        query=req.query,
        history=req.history,
        preferred_entity=req.preferred_entity,
        memory_context=memory_context
    )

    return ClassifyResponse(
        category=result.category,
        reasoning=result.reasoning,
        memory_used=bool(memory_context),
        retrieved_context=memory_context if memory_context else "暂无相关历史经验"
    )

@router.post("/feedback")
async def feedback(
    req: FeedbackRequest, 
    background_tasks: BackgroundTasks,
    request: Request
):
    """
    异步处理反馈，调用 ReMe 写入记忆
    """
    reme_app = getattr(request.app.state, "reme_app", None)
    if not reme_app:
        return {"status": "skipped", "reason": "ReMe not initialized"}

    async def _process_feedback():
        try:
            print(f"🧠 Learning: {req.query} -> {req.correct_category.value}")
            await reme_app.async_execute(
                name="summary_task_memory",
                workspace_id=settings.UNIFIED_WORKSPACE_ID,
                trajectories=[{
                    "messages": [
                        {"role": "user", "content": req.query},
                        {"role": "assistant", "content": f"Category: {req.correct_category.value}\nReason: {req.reason}"}
                    ],
                    "score": 1.0
                }]
            )
        except Exception as e:
            print(f"❌ Learning Failed: {e}")

    background_tasks.add_task(_process_feedback)
    return {"status": "processing"}

# ================= Cache Endpoints =================

@router.post("/cache/check", response_model=CacheCheckResponse)
async def check_cache(
    req: CacheCheckRequest,
    service: CacheService = Depends(get_cache_service)
):
    return await service.check_cache(
        query=req.query,
        history=req.history,
        preferred_entity=req.preferred_entity
    )


# 定义需要剔除的敏感字段黑名单
CONTEXT_KEYS_BLACKLIST = {
    "user_id", "team_id", "userid", "teamid", 
    "session_id", "message_id", "unique_id",
    "trace_id", "authorization"
}
def recursive_clean(data: Any, blacklist: set) -> Any:
    if isinstance(data, dict):
        return {
            k: recursive_clean(v, blacklist)
            for k, v in data.items()
            if k.lower() not in blacklist
        }
    elif isinstance(data, list):
        return [recursive_clean(item, blacklist) for item in data]
    return data
@router.post("/cache/save")
async def save_cache(
    req: SaveCacheRequest,
    service: CacheService = Depends(get_cache_service)
):
    # [新增] 自动清洗：从 final_json 中剔除上下文敏感参数
    clean_params = recursive_clean(req.final_json, CONTEXT_KEYS_BLACKLIST)

    await service.save_execution(
        query=req.query,
        history=req.history,
        preferred_entity=req.preferred_entity,
        agent_type=req.agent_type,
        route_key=req.route_key,
        params=clean_params  # 存入清洗后的参数
    )
    return {"status": "success"}

# ================= Maintenance Endpoints =================

@router.post("/maintenance/memory")
async def upsert_memory(
    req: MemoryMaintainRequest,
    service: MemoryService = Depends(get_memory_service)
):
    uid = await service.upsert_memory(req)
    return {"status": "success", "id": uid}

@router.get("/maintenance/list")
async def list_memories(
    workspace_id: str = settings.UNIFIED_WORKSPACE_ID,
    limit: int = 100,
    service: MemoryService = Depends(get_memory_service)
):
    items = await service.list_memories(workspace_id, limit)
    return {
        "workspace_id": workspace_id,
        "total": len(items),
        "items": items
    }

@router.post("/maintenance/clear")
async def clear_memories(
    workspace_id: str = settings.UNIFIED_WORKSPACE_ID,
    service: MemoryService = Depends(get_memory_service)
):
    await service.clear_workspace(workspace_id)
    return {"status": "success", "message": f"Workspace {workspace_id} cleared."}

@router.get("/maintenance/export")
async def export_memories(
    workspace_id: str = settings.UNIFIED_WORKSPACE_ID,
    service: MemoryService = Depends(get_memory_service)
):
    filename = f"backup_{workspace_id}.jsonl"
    return StreamingResponse(
        service.export_jsonl_stream(workspace_id),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.post("/maintenance/import_jsonl")
async def import_jsonl(
    file: UploadFile = File(...), 
    workspace_id_override: Optional[str] = None,
    service: MemoryService = Depends(get_memory_service)
):
    count = 0
    batch = []
    
    # --- [修改开始] ---
    # 1. 一次性读取文件内容 (FastAPI 的 read 是异步的)
    content = await file.read()
    
    # 2. 按行分割并遍历
    lines = content.decode("utf-8").splitlines()
    
    for line_str in lines:
        line_str = line_str.strip()
        if not line_str: continue
        
        try:
            raw = json.loads(line_str)
            raw_meta = raw.get("metadata", {})
            wid = workspace_id_override or raw.get("workspace_id", settings.UNIFIED_WORKSPACE_ID)
            uid = raw.get("unique_id")

            if "metadata" in raw_meta and isinstance(raw_meta["metadata"], str):
                 node = VectorNode(
                    unique_id=uid, workspace_id=wid,
                    content=raw.get("content"), metadata=raw_meta, vector=[]
                )
            else:
                trigger = raw.get("content")
                answer = raw_meta.get("content") or raw.get("answer") or "No Content"
                node = service._construct_node(
                    workspace_id=wid, unique_id=uid or "batch_gen", 
                    trigger=trigger, answer=answer, tags=raw_meta.get("tags", []), author="batch"
                )
            
            batch.append(node)
            count += 1
            
            if len(batch) >= 10:
                await service.batch_import(batch)
                batch = []
                
        except Exception as e:
            print(f"⚠️ Import skipping line: {e}")

    if batch:
        await service.batch_import(batch)
        
    return {"status": "success", "imported": count}


@router.get("/cache/list")
async def list_cache(
    limit: int = 50,
    service: CacheService = Depends(get_cache_service)
):
    """
    查看当前所有的缓存记录 (已格式化 JSON)
    """
    try:
        items = await service.list_cache_entries(limit=limit)
        return {
            "total": len(items),
            "items": items
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/cache/flush/all")
async def flush_cache(
    service: CacheService = Depends(get_cache_service)
):
    """
    🔥 [高危] 清空所有缓存数据
    """
    success = await service.flush_all_cache()
    if success:
        return {"status": "success", "message": "All cache entries have been wiped."}
    else:
        raise HTTPException(status_code=500, detail="Failed to flush cache.")

@router.delete("/cache/{unique_id}")
async def delete_cache_item(
    unique_id: str,
    service: CacheService = Depends(get_cache_service)
):
    """
    删除指定的缓存 ID
    """
    success = await service.delete_cache_entry(unique_id)
    if success:
        return {"status": "success", "message": f"Cache entry {unique_id} deleted."}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete entry. It might not exist.")