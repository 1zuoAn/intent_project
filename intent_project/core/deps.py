# intent_project/core/deps.py
from typing import Optional
from openai import AsyncOpenAI

# 引入我们刚才定义的配置
from intent_project.core.config import settings

# 引入 flowllm 组件
from flowllm.core.embedding_model.openai_compatible_embedding_model import OpenAICompatibleEmbeddingModel
from flowllm.core.vector_store.es_vector_store import EsVectorStore

# === 全局单例变量 (私有) ===
_llm_client: Optional[AsyncOpenAI] = None
_maintenance_vs: Optional[EsVectorStore] = None

# ================= 资源生命周期管理 =================

def init_resources():
    """在 App 启动时调用：初始化连接池"""
    global _llm_client, _maintenance_vs
    
    print("🚀 [Deps] Initializing Global Resources...")
    
    # 1. 初始化 LLM Client
    if settings.REAL_LLM_KEY:
        _llm_client = AsyncOpenAI(
            api_key=settings.REAL_LLM_KEY,
            base_url=settings.REAL_LLM_URL
        )
        print("   ✅ AsyncOpenAI Client Ready")
    else:
        print("   ⚠️ AsyncOpenAI Client Skipped (Key missing)")

    # 2. 初始化 Maintenance Vector Store (用于 Cache 和 维护接口)
    #    (ReMeApp 会自己管理它内部的 VS，这里初始化的这个是给 CacheService 用的)
    if settings.ES_URL and settings.DASHSCOPE_API_KEY:
        try:
            # 独立初始化 Embedding 模型
            embedding_model = OpenAICompatibleEmbeddingModel(
                model_name=settings.DASHSCOPE_EMBEDDING_MODEL,
                api_key=settings.DASHSCOPE_API_KEY,
                base_url=settings.DASHSCOPE_BASE_URL
            )
            
            # 独立初始化 ES 连接
            _maintenance_vs = EsVectorStore(
                hosts=[f"http://{settings.ES_HOST}"],           
                basic_auth=(settings.ES_USER, settings.ES_PASS),
                embedding_model=embedding_model
            )
            print("   ✅ Maintenance VectorStore Ready")
        except Exception as e:
            print(f"   ❌ Maintenance VectorStore Init Failed: {e}")
    else:
        print("   ⚠️ Maintenance VectorStore Skipped (Missing Config)")


async def close_resources():
    """在 App 关闭时调用：清理资源"""
    global _llm_client, _maintenance_vs
    
    print("🛑 [Deps] Closing Resources...")
    
    if _llm_client:
        await _llm_client.close()
        print("   ✅ LLM Client Closed")
    
    if _maintenance_vs:
        await _maintenance_vs.async_close()
        print("   ✅ VectorStore Connection Closed")


# ================= 依赖注入函数 (Getters) =================

def get_llm_client() -> AsyncOpenAI:
    """获取全局共享的 OpenAI Client"""
    if _llm_client is None:
        raise RuntimeError("Global LLM Client is not initialized!")
    return _llm_client

def get_vector_store() -> EsVectorStore:
    """获取全局共享的 ES VectorStore"""
    if _maintenance_vs is None:
        raise RuntimeError("Global VectorStore is not initialized!")
    return _maintenance_vs