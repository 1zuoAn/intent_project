# intent_project/schemas/base.py
from enum import Enum
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field

# ================= Enums & Types =================
AgentType = Literal["zhiyi", "douyi", "abroad"]

class IntentEnum(str, Enum):
    IMAGE_SEARCH = "图搜"
    SELECTION = "选品"
    IMAGE_DESIGN = "生图改图"
    TRENDS = "趋势报告"
    MEDIA = "媒体"
    SHOP = "店铺"
    SCHEDULE = "定时任务"
    CHATBOT = "聊天机器人"

# ================= Cache Models =================
class CacheCheckRequest(BaseModel):
    query: str
    history: Optional[str] = ""
    preferred_entity: Optional[str] = None 

class CacheCheckResponse(BaseModel):
    hit: bool = Field(..., description="是否命中缓存")
    agent_type: Optional[AgentType] = None
    # [新增] 告诉调用方用哪个接口
    route_key: Optional[str] = Field(None, description="命中的路由标识") 
    final_params: Optional[Dict[str, Any]] = Field(None, description="修补时间后的最终可用参数")
    reason: str
    score: float = 0.0

class SaveCacheRequest(BaseModel):
    query: str
    history: Optional[str] = ""
    preferred_entity: Optional[str] = None
    agent_type: AgentType
    final_json: Dict[str, Any]
    route_key: str = Field(..., description="例如: zhiyi_shop, zhiyi_general, douyi_default")

# ================= Classification Models =================
class ClassifyResult(BaseModel):
    category: IntentEnum = Field(..., description="必须是预定义类别之一")
    reasoning: str = Field(..., description="简短的推理过程")

class ClassifyRequest(BaseModel):
    query: str
    preferred_entity: Optional[str] = None
    history: Optional[str] = None

class ClassifyResponse(ClassifyResult):
    memory_used: bool
    retrieved_context: Optional[str] = None

class FeedbackRequest(BaseModel):
    query: str
    correct_category: IntentEnum
    reason: str

# 统一只保留这一个定义
CLASSIFY_JSON_SCHEMA = {
    "name": "classify_intent",
    "schema": ClassifyResult.model_json_schema(),
    "strict": True 
}

# ================= Maintenance Models =================
class MemoryMaintainRequest(BaseModel):
    workspace_id: str = Field(..., description="工作区ID，例如 intent_router_v2")
    unique_id: Optional[str] = Field(None, description="记忆ID，如果不传则新建")
    when_to_use: str = Field(..., description="检索触发条件 (Query/Key)，将用于生成向量")
    content: str = Field(..., description="具体的记忆内容/回答")
    category: str = Field("task", description="记忆类型: task, personal, tool")
    score: float = Field(1.0, description="置信度分数")
    tags: List[str] = Field(default_factory=list, description="标签")

# ================= LLM Judge Models =================
class JudgeResult(BaseModel):
    reusable: bool = Field(..., description="是否可以复用参数")
    reason: str = Field(..., description="判断理由")

class TimeResult(BaseModel):
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")
    # [新增] 必须让 LLM 提取季节文本，否则抖衣接口会挂
    year_season: Optional[str] = Field(None, description="如果查询包含特定年份季节(如'2025年春季')，请提取该标准字符串；否则留空")