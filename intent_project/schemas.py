from enum import Enum
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
# 定义 Agent 类型枚举
AgentType = Literal["zhiyi", "douyi", "abroad"]

# --- 缓存相关的模型 ---

class CacheCheckRequest(BaseModel):
    query: str
    history: Optional[str] = ""
    preferred_entity: Optional[str] = None # 用于构建检索 Key

class CacheCheckResponse(BaseModel):
    hit: bool = Field(..., description="是否命中缓存")
    agent_type: Optional[AgentType] = None
    final_params: Optional[Dict[str, Any]] = Field(None, description="修补时间后的最终可用参数")
    reason: str = Field(..., description="命中或未命中的理由")
    score: float = Field(0.0, description="向量相似度得分")

class SaveCacheRequest(BaseModel):
    query: str
    history: Optional[str] = ""
    preferred_entity: Optional[str] = None
    agent_type: AgentType
    final_json: Dict[str, Any]
    
class IntentEnum(str, Enum):
    IMAGE_SEARCH = "图搜"
    SELECTION = "选品"
    IMAGE_DESIGN = "生图改图"
    TRENDS = "趋势报告"
    MEDIA = "媒体"
    SHOP = "店铺"
    SCHEDULE = "定时任务"
    CHATBOT = "聊天机器人"

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

CLASSIFY_JSON_SCHEMA = {
    "name": "classify_intent",
    "schema": ClassifyResult.model_json_schema(),
    "strict": True 
}

class MemoryMaintainRequest(BaseModel):
    workspace_id: str = Field(..., description="工作区ID，例如 intent_router_v2")
    unique_id: Optional[str] = Field(None, description="记忆ID，如果不传则新建")
    
    # 核心检索字段 (用于生成向量)
    when_to_use: str = Field(..., description="检索触发条件 (Query/Key)，将用于生成向量")
    
    # 记忆主体内容
    content: str = Field(..., description="具体的记忆内容/回答")
    
    # 其他元数据
    category: str = Field("task", description="记忆类型: task, personal, tool")
    score: float = Field(1.0, description="置信度分数")
    tags: List[str] = Field(default_factory=list, description="标签")

CLASSIFY_JSON_SCHEMA = {
    "name": "classify_intent",
    "schema": ClassifyResult.model_json_schema(),
    "strict": True 
}

class JudgeResult(BaseModel):
    reusable: bool = Field(..., description="是否可以复用参数")
    reason: str = Field(..., description="判断理由")

class TimeResult(BaseModel):
    """
    时间校准结果的超集模型。
    包含所有平台可能用到的时间字段，模型只需填充相关的，其他留空。
    """
    # 知衣字段
    startTime: Optional[str] = Field(None, description="开始时间 (YYYY-MM-DD)")
    endTime: Optional[str] = Field(None, description="结束时间 (YYYY-MM-DD)")
    # 抖衣字段
    dateRange: Optional[str] = Field(None, description="日期范围 (YYYYMMDD-YYYYMMDD)")
    # 海外探款字段
    putOnSaleStartDate: Optional[str] = Field(None, description="上架开始时间 (YYYY-MM-DD)")
    putOnSaleEndDate: Optional[str] = Field(None, description="上架结束时间 (YYYY-MM-DD)")