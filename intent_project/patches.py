import warnings
import json
from typing import List, Any
from loguru import logger
from elasticsearch import NotFoundError

# 导入原本的库
from flowllm.core.vector_store.es_vector_store import EsVectorStore
from flowllm.core.schema import VectorNode

warnings.filterwarnings("ignore")

def apply_monkey_patches():
    print("🔧 Applying Monkey Patches...")

    # =========================================================
    # Patch 1: async_exist_workspace (修复 HEAD 请求问题)
    # =========================================================
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

    print("🔧 Applying Monkey Patch 1: EsVectorStore (HEAD -> GET)...")
    EsVectorStore.async_exist_workspace = async_exist_workspace_patched

    # =========================================================
    # Patch 2: async_search (核心修复：替换 script_score 为原生 knn)
    # =========================================================
    async def async_search_patched(self, workspace_id: str, query: str, top_k: int = 5, score_threshold: float = 0.0, **kwargs) -> List[VectorNode]:
        """
        替代 flowllm 原生的 script_score 查询，改用 ES 8.x/Serverless 标准 kNN 查询。
        解决 'request contains not allowed script' 错误。
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
                
                # 手动过滤分数 (score_threshold)
                if score < score_threshold:
                    continue

                source = hit.get("_source", {})
                
                # 构造 VectorNode
                node = VectorNode(
                    unique_id=hit.get("_id"),
                    workspace_id=workspace_id,
                    content=source.get("content"),
                    metadata=source.get("metadata", {}),
                    vector=[], # vector 已被排除
                )
                
                # [关键修复] 将 score 注入到 metadata 中，而不是作为属性赋值
                # Pydantic 模型不支持动态属性赋值，会导致 ValueError
                if node.metadata is None:
                    node.metadata = {}
                node.metadata["_score"] = score 
                
                nodes.append(node)

            return nodes

        except Exception as e:
            logger.error(f"⚠️ [Patch] kNN search failed: {e}")
            raise e

    print("🔧 Applying Monkey Patch 2: EsVectorStore (script_score -> native knn)...")
    EsVectorStore.async_search = async_search_patched

    print("✅ All Monkey Patches Applied.")