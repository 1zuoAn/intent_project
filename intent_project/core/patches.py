# intent_project/core/patches.py
import warnings
from typing import List
from loguru import logger
from elasticsearch import NotFoundError
from datetime import datetime

# 导入 flowllm/reme 依赖
from flowllm.core.vector_store.es_vector_store import EsVectorStore
from reme_ai.summary.task.memory_deduplication_op import MemoryDeduplicationOp
from reme_ai.vector_store.recall_vector_store_op import RecallVectorStoreOp
from reme_ai.schema.memory import vector_node_to_memory, BaseMemory
from flowllm.core.schema import VectorNode

warnings.filterwarnings("ignore")

def apply_monkey_patches():
    print("🔧 Applying Monkey Patches...")

    # --- Patch 1: async_exist_workspace (HEAD -> GET) ---
    async def async_exist_workspace_patched(self, workspace_id: str) -> bool:
        try:
            await self._async_client.indices.get(index=workspace_id)
            return True
        except NotFoundError:
            return False
        except Exception as e:
            if "index_not_found" in str(e):
                return False
            logger.warning(f"⚠️ [Patch] Check index failed: {e}")
            raise e

    EsVectorStore.async_exist_workspace = async_exist_workspace_patched
    print("✅ Patch 1 Applied.")

    # --- Patch 2: MemoryDeduplicationOp ---
    async def _get_existing_task_memory_embeddings_patched(self, workspace_id: str) -> List[List[float]]:
        try:
            if not hasattr(self, "vector_store") or not self.vector_store or not workspace_id:
                return []
            logger.debug(f"Fetching existing nodes via iterator for workspace: {workspace_id}...")
            # 注意：这里调用的是下面 Patch 4 定义的方法
            existing_nodes = await self.vector_store.async_list_workspace_nodes(workspace_id=workspace_id)

            existing_embeddings = []
            for node in existing_nodes:
                if hasattr(node, "embedding") and node.embedding:
                    existing_embeddings.append(node.embedding)
                elif hasattr(node, "vector") and node.vector: 
                    existing_embeddings.append(node.vector)

            max_memories = self.op_params.get("max_existing_task_memories", 1000)
            if len(existing_embeddings) > max_memories:
                existing_embeddings = existing_embeddings[:max_memories]
            return existing_embeddings
        except Exception as e:
            logger.warning(f"Failed to retrieve existing task memory embeddings: {e}")
            return []

    MemoryDeduplicationOp._get_existing_task_memory_embeddings = _get_existing_task_memory_embeddings_patched
    print("✅ Patch 2 Applied.")

    # --- Patch 3: RecallVectorStoreOp (ES Serverless KNN Fix) ---
    async def async_execute_recall_patched(self):
        try:
            recall_key: str = self.op_params.get("recall_key", "query")
            top_k: int = self.context.get("top_k", 3)
            query: str = self.context.get(recall_key)
            workspace_id: str = self.context.workspace_id

            if not query:
                self.context.response.metadata["memory_list"] = []
                return

            if hasattr(self.vector_store, "embedding_model") and self.vector_store.embedding_model:
                embeddings = self.vector_store.embedding_model.get_embeddings([query])
                if not embeddings:
                    self.context.response.metadata["memory_list"] = []
                    return
                query_vector = embeddings[0]
            else:
                self.context.response.metadata["memory_list"] = []
                return

            search_body = {
                "knn": {
                    "field": "vector",
                    "query_vector": query_vector,
                    "k": top_k,
                    "num_candidates": max(100, top_k * 10)
                },
                "_source": True 
            }

            resp = await self.vector_store._async_client.search(
                index=workspace_id,
                body=search_body,
                size=top_k
            )

            memory_list: List[BaseMemory] = []
            hits = resp.get("hits", {}).get("hits", [])
            
            for hit in hits:
                source = hit.get("_source", {})
                try:
                    meta = source.get("metadata", {})
                    if not isinstance(meta, dict): meta = {}
                    if "time_created" not in meta: meta["time_created"] = datetime.now().isoformat()
                    if "memory_type" not in meta: meta["memory_type"] = "task"

                    node = VectorNode(
                        unique_id=hit.get("_id"), 
                        workspace_id=source.get("workspace_id"),
                        content=source.get("content"),
                        metadata=meta,
                        vector=None 
                    )
                    memory = vector_node_to_memory(node)
                    memory.score = hit.get("_score")
                    memory_list.append(memory)
                except Exception as e:
                    logger.warning(f"Failed to parse memory hit: {e}")

            self.context.response.metadata["memory_list"] = memory_list

        except Exception as e:
            logger.error(f"Error in Patched RecallVectorStoreOp: {e}")
            self.context.response.metadata["memory_list"] = []

    RecallVectorStoreOp.async_execute = async_execute_recall_patched
    print("✅ Patch 3 Applied.")

    # --- Patch 4: EsVectorStore 缺失方法修复 (async_list_workspace_nodes) ---
    # [关键] 这就是你原本代码里能跑通的原因，一定要保留！
    async def async_list_workspace_nodes_patched(self, workspace_id: str, max_size: int = 10000, **kwargs) -> List[VectorNode]:
        try:
            if not await self.async_exist_workspace(workspace_id=workspace_id):
                return []

            resp = await self._async_client.search(
                index=workspace_id,
                body={"query": {"match_all": {}}, "size": max_size}
            )
            
            nodes = []
            hits = resp.get("hits", {}).get("hits", [])
            for hit in hits:
                source = hit.get("_source", {})
                node = VectorNode(
                    unique_id=hit.get("_id"),
                    workspace_id=workspace_id,
                    content=source.get("content"),
                    metadata=source.get("metadata", {}),
                    vector=source.get("vector") 
                )
                nodes.append(node)
            return nodes
        except Exception as e:
            logger.error(f"Failed to list nodes (Patched): {e}")
            raise e

    EsVectorStore.async_list_workspace_nodes = async_list_workspace_nodes_patched
    print("✅ Patch 4 Applied.")
    async def async_search_patched(self, workspace_id: str, query: str, top_k: int = 5, score_threshold: float = 0.0, **kwargs) -> List[VectorNode]:
        """
        替代 flowllm 原生的 script_score 查询，改用 ES 8.x/Serverless 标准 kNN 查询。
        """
        try:
            # 1. 生成向量
            if not self.embedding_model:
                raise ValueError("Embedding model is not initialized")
            
            embeddings = self.embedding_model.get_embeddings([query])
            if not embeddings:
                return []
            query_vector = embeddings[0]

            # 2. 构造 kNN 查询 (阿里云 Serverless 兼容格式)
            body = {
                "knn": {
                    "field": "vector",
                    "query_vector": query_vector,
                    "k": top_k,
                    "num_candidates": max(top_k * 10, 100)
                },
                "_source": {
                    "excludes": ["vector"] # 不返回向量数据，减少传输
                }
            }

            # 3. 执行搜索
            resp = await self._async_client.search(
                index=workspace_id, 
                body=body
            )

            # 4. 解析结果
            nodes = []
            for hit in resp.get("hits", {}).get("hits", []):
                score = hit.get("_score", 0.0)
                
                # 手动过滤分数
                if score < score_threshold:
                    continue

                source = hit.get("_source", {})
                
                node = VectorNode(
                    unique_id=hit.get("_id"),
                    workspace_id=workspace_id,
                    content=source.get("content"),
                    metadata=source.get("metadata", {}),
                    vector=[], 
                )
                
                # [Patch] 注入分数到 metadata
                if node.metadata is None:
                    node.metadata = {}
                node.metadata["_score"] = score 
                
                nodes.append(node)

            return nodes

        except Exception as e:
            logger.error(f"⚠️ [Patch] kNN search failed: {e}")
            raise e

    # 应用 Patch
    EsVectorStore.async_exist_workspace = async_exist_workspace_patched
    EsVectorStore.async_search = async_search_patched
    print("✅ [Patches] Applied successfully.")