# main.py
import os
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from reme_ai import ReMeApp

# 引入模块
from intent_project.core.config import settings
from intent_project.core.patches import apply_monkey_patches
from intent_project.core import deps
from intent_project.api.routes import router as api_router

# 1. 应用 Patch (最优先)
apply_monkey_patches()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- 启动阶段 ---
    
    # A. 初始化通用资源 (LLM Client, Cache VS)
    deps.init_resources()
    
    # B. 初始化 ReMe (ReMe 是独立的 SDK 实例)
    print("🚀 [Main] Initializing ReMe App...")
    
    # 设置 ReMe 环境变量
    os.environ["FLOW_LLM_API_KEY"] = settings.REAL_LLM_KEY or ""
    os.environ["FLOW_LLM_BASE_URL"] = settings.REAL_LLM_URL
    os.environ["FLOW_EMBEDDING_API_KEY"] = settings.DASHSCOPE_API_KEY or "dummy"
    os.environ["FLOW_EMBEDDING_BASE_URL"] = settings.DASHSCOPE_BASE_URL

    es_params = json.dumps({"hosts": settings.ES_URL})
    
    reme_app = ReMeApp(
        f"llm.default.api_key={settings.REAL_LLM_KEY}",
        f"llm.default.base_url={settings.REAL_LLM_URL}",
        f"llm.default.model_name={settings.REAL_LLM_MODEL}",
        "llm.default.backend=openai_compatible",
        
        f"embedding_model.default.model_name={settings.DASHSCOPE_EMBEDDING_MODEL}", 
        "embedding_model.default.backend=openai_compatible",               
        
        "vector_store.default.backend=elasticsearch",
        f"vector_store.default.params={es_params}",
    )
    
    try:
        await reme_app.async_start()
        # [关键] 将 ReMe 挂载到 app.state，供 Route 使用
        app.state.reme_app = reme_app
        print("✅ ReMe App Started.")
    except Exception as e:
        print(f"❌ ReMe Start Failed: {e}")
        app.state.reme_app = None

    yield
    
    # --- 关闭阶段 ---
    print("🛑 [Main] Shutting down...")
    
    # 关闭 ReMe
    if app.state.reme_app:
        await app.state.reme_app.async_stop()
    
    # 关闭通用资源
    await deps.close_resources()

app = FastAPI(title="Intent Router Pro", lifespan=lifespan)

# 注册路由
app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)