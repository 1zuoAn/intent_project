# intent_project/services/memory_service.py
import json
from uuid import uuid4
from datetime import datetime
from typing import List, AsyncGenerator

from flowllm.core.vector_store.es_vector_store import EsVectorStore
from flowllm.core.schema import VectorNode
from intent_project.schemas.base import MemoryMaintainRequest

class MemoryService:
    def __init__(self, vector_store: EsVectorStore):
        self.vs = vector_store

    def _construct_standard_node(
        self,
        workspace_id: str,
        unique_id: str,
        when_to_use: str,
        answer: str,
        tags: List[str],
        author: str = "manual"
    ) -> VectorNode:
        """
        [完全还原] 构造符合 ReMe/ES 标准的 VectorNode 结构 
        (包含嵌套的 Stringified JSON Metadata)
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 1. 构造内层 Metadata (ReMe 需要这个来反序列化)
        inner_meta_dict = {
            "when_to_use": when_to_use,
            "experience": answer,
            "tags": tags,
            "confidence": 1.0,
            "step_type": "decision",
            "tools_used": []
        }
        
        # 2. 构造外层 Metadata (ES 存储用)
        outer_meta = {
            "memory_type": "task",
            "content": answer,
            "score": 1.0,
            "time_created": now_str,
            "time_modified": now_str,
            "author": author,
            # [关键] 内层字典序列化为字符串
            "metadata": json.dumps(inner_meta_dict, ensure_ascii=False) 
        }

        return VectorNode(
            unique_id=unique_id,
            workspace_id=workspace_id,
            content=when_to_use,    # [关键] 外层 Content 放 Trigger
            metadata=outer_meta,
            vector=None
        )

    async def upsert_memory(self, req: MemoryMaintainRequest) -> str:
        final_uid = req.unique_id if req.unique_id else uuid4().hex
        
        # 使用还原后的构造逻辑
        node = self._construct_standard_node(
            workspace_id=req.workspace_id,
            unique_id=final_uid,
            when_to_use=req.when_to_use,
            answer=req.content,
            tags=req.tags,
            author="api_manual"
        )

        # 生成向量
        if self.vs.embedding_model:
            emb = self.vs.embedding_model.get_embeddings([node.content])
            if emb:
                node.vector = emb[0]

        await self.vs.async_insert([node], workspace_id=req.workspace_id)
        return final_uid

    async def list_memories(self, workspace_id: str, limit: int = 100) -> List[dict]:
        """
        [关键修复] 直接调用 Patch 4 注入的 async_list_workspace_nodes 方法
        """
        # 这个方法现在存在了，因为我们在 patches.py 里注入了它
        nodes = await self.vs.async_list_workspace_nodes(workspace_id=workspace_id, max_size=limit)
        
        results = []
        for n in nodes:
            d = n.model_dump()
            d.pop("vector", None)
            results.append(d)
        return results

    async def clear_workspace(self, workspace_id: str):
        # 使用 Patch 1 注入的 async_exist_workspace
        if await self.vs.async_exist_workspace(workspace_id):
            await self.vs.async_delete_workspace(workspace_id)
        await self.vs.async_create_workspace(workspace_id)

    async def export_jsonl_stream(self, workspace_id: str) -> AsyncGenerator[str, None]:
        # 同样直接调用 Patch 4 的方法
        nodes = await self.vs.async_list_workspace_nodes(workspace_id=workspace_id, max_size=10000)
        for node in nodes:
            d = node.model_dump()
            d["vector"] = []
            yield json.dumps(d, ensure_ascii=False) + "\n"

    async def batch_import(self, nodes: List[VectorNode]):
        """批量导入辅助函数 (还原 main.py 里的 _batch_insert 逻辑)"""
        if not nodes: return
        
        texts = [n.content for n in nodes]
        if self.vs.embedding_model:
            embeddings = self.vs.embedding_model.get_embeddings(texts)
            for i, node in enumerate(nodes):
                if i < len(embeddings):
                    node.vector = embeddings[i]
        
        await self.vs.async_insert(nodes, workspace_id=nodes[0].workspace_id)
        