# intent_project/core/config.py
import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

class Settings:
    # ================= LLM 配置 =================
    REAL_LLM_KEY = os.getenv("OPENROUTER_API_KEY")
    REAL_LLM_URL = os.getenv("REAL_LLM_URL", "https://openrouter.ai/api/v1")
    REAL_LLM_MODEL = os.getenv("REAL_LLM_MODEL", "google/gemini-2.0-flash-001") # 更新了默认模型名，建议用最新的

    # ================= 阿里 DashScope 配置 =================
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
    DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    DASHSCOPE_EMBEDDING_MODEL = os.getenv("DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v3")

    # ================= Elasticsearch 配置 =================
    ES_USER = os.getenv("ES_USER")
    ES_PASS = os.getenv("ES_PASS")
    ES_HOST = os.getenv("ES_HOST")
    
    # 自动拼接完整 URL
    @property
    def ES_URL(self):
        if self.ES_USER and self.ES_PASS and self.ES_HOST:
            return f"http://{self.ES_USER}:{self.ES_PASS}@{self.ES_HOST}"
        return None

    # ================= 业务常量 =================
    UNIFIED_WORKSPACE_ID = "intent_router_v2"
    CACHE_WORKSPACE_ID = "agent_param_cache_v1"

# 实例化单例，方便其他文件直接 import settings
settings = Settings()