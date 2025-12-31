import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4

from schemas import CacheCheckResponse, AgentType

# 引用现有依赖
from flowllm.core.vector_store.es_vector_store import EsVectorStore
from flowllm.core.schema import VectorNode 
from openai import AsyncOpenAI
from schemas import JudgeResult,TimeResult
import config

# 初始化用于裁判和时间提取的 Fast LLM
llm_client = AsyncOpenAI(
    api_key=config.REAL_LLM_KEY, 
    base_url=config.REAL_LLM_URL
)
FAST_LLM_MODEL = config.REAL_LLM_MODEL

class CacheService:
    def __init__(self, vector_store: EsVectorStore):
        self.vs = vector_store
        self.workspace_id = "agent_param_cache_v1"

    def _construct_vector_key(self, query: str, preferred_entity: Optional[str], history: Optional[str]) -> str:
        """[核心] 统一构建向量索引 Key"""
        entity_str = preferred_entity if preferred_entity else "无偏好"
        history_str = history[-500:] if history else "无历史记录"
        return f"用户当前查询: {query}；偏好平台: {entity_str}；对话历史摘要: {history_str}"

    async def check_cache(self, query: str, history: str = "", preferred_entity: str = None) -> CacheCheckResponse:
        """执行：检索 -> 分级判定 -> 时间校准"""
        search_text = self._construct_vector_key(query, preferred_entity, history)

        # 向量检索 (配合 patches.py 使用 top_k)
        results = await self.vs.async_search(
            workspace_id=self.workspace_id,
            query=search_text,
            top_k=1 
        )

        if not results:
            return CacheCheckResponse(hit=False, reason="Tier 3: No results found", score=0.0)

        best_match = results[0]
        
        # 从 metadata 读取分数
        score = best_match.metadata.get("_score", 0.0)
        
        # 手动过滤分数
        if score < 0.90:
             return CacheCheckResponse(hit=False, reason="Tier 3: Low similarity (<0.90)", score=score)
        
        try:
            cached_data = json.loads(best_match.metadata["cached_payload_json"])
            cached_params = cached_data["api_params"]
            cached_agent_type = cached_data["agent_type"]
            cached_query = cached_data["original_query"]
        except Exception as e:
            return CacheCheckResponse(hit=False, reason=f"Cache Data Corrupted: {e}", score=score)

        print(f"🔍 [Cache Search] Score: {score:.4f} | Agent: {cached_agent_type}")

        # --- Tier 1: 完美匹配 (>= 0.99) ---
        if score >= 0.99:
            final_params = await self._calibrate_time(query, cached_agent_type, cached_params)
            return CacheCheckResponse(
                hit=True, 
                agent_type=cached_agent_type, 
                final_params=final_params, 
                reason="Tier 1: Exact Match (Direct Hit)", 
                score=score
            )

        # --- Tier 2: 高度相似 (0.90 <= score < 0.99) ---
        is_reusable = await self._llm_judge(query, cached_query, cached_params, preferred_entity)
        
        if is_reusable:
            final_params = await self._calibrate_time(query, cached_agent_type, cached_params)
            return CacheCheckResponse(
                hit=True, 
                agent_type=cached_agent_type, 
                final_params=final_params, 
                reason="Tier 2: Judge Approved", 
                score=score
            )
        else:
            return CacheCheckResponse(hit=False, reason="Tier 2: Judge Rejected (Attribute Mismatch)", score=score)

    async def save_execution(self, query: str, history: str, preferred_entity: str, agent_type: str, params: Dict[str, Any]):
        """保存缓存"""
        vector_text = self._construct_vector_key(query, preferred_entity, history)
        
        payload = {
            "agent_type": agent_type,
            "original_query": query,
            "api_params": params
        }
        
        metadata = {
            "agent_type": agent_type,
            "cached_payload_json": json.dumps(payload, ensure_ascii=False)
        }

        node = VectorNode(
            unique_id=str(uuid4()),
            workspace_id=self.workspace_id,
            content=vector_text,
            metadata=metadata,
            vector=[] 
        )

        # 手动生成向量
        if self.vs.embedding_model:
            try:
                emb = self.vs.embedding_model.get_embeddings([vector_text])
                if emb:
                    node.vector = emb[0]
            except Exception as e:
                print(f"⚠️ Embedding generation failed: {e}")
                raise e

        await self.vs.async_insert(nodes=[node], workspace_id=self.workspace_id)
        print(f"💾 [Cache Saved] {agent_type}: {query[:20]}...")

    # ==========================================
    # LLM 内部逻辑 (Strict Schema Mode)
    # ==========================================

    async def _llm_judge(self, current_query: str, cached_query: str, cached_params: Dict, current_entity: str) -> bool:
        """
        裁判：严格校验属性，仅允许时间差异。
        使用 JudgeResult Pydantic Schema。
        """
        prompt = f"""
        你是一个极其严格的参数复用裁判。
        任务：判断【当前意图】是否可以完全复用【历史意图】的参数模板（仅允许时间不同）。

        [历史查询]: {cached_query}
        [参考参数]: {json.dumps(cached_params, ensure_ascii=False)}
        [当前查询]: {current_query}
        [当前偏好]: {current_entity if current_entity else "无"}

        判决规则：
        1. **允许差异**：仅允许“时间”、“日期”、“最近多少天”这种时间维度的差异。
        2. **绝对禁止差异**：
           - 品类不同（如“连衣裙” vs “半身裙”） -> REJECT
           - 颜色/材质/风格不同 -> REJECT
           - 排序方式不同 -> REJECT
           - 平台不同（如“知衣” vs “抖音”） -> REJECT
           - 价格区间不同 -> REJECT
        
        如果除了时间以外的任何条件有偏差，必须返回 false。
        """
        
        try:
            response = await llm_client.chat.completions.create(
                model=FAST_LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                # [关键更新] 使用 strict json_schema
                extra_body={
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "judge_result",
                            "schema": JudgeResult.model_json_schema(),
                            "strict": True
                        }
                    }
                },
                temperature=0.0
            )
            
            content = response.choices[0].message.content
            # 使用 Pydantic 解析验证
            result = JudgeResult.model_validate_json(content)
            
            if not result.reusable:
                print(f"🚫 Judge Rejected: {result.reason}")
            
            return result.reusable

        except Exception as e:
            print(f"⚠️ Judge Error: {e}")
            return False

    async def _calibrate_time(self, current_query: str, agent_type: str, cached_params: Dict) -> Dict:
        """
        时间校准：基于当前 Query 重新提取时间。
        使用 TimeResult Pydantic Schema (Superset)。
        """
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        format_instructions = {
            "zhiyi": '请仅填充 startTime 和 endTime。',
            "douyi": '请仅填充 dateRange。',
            "abroad": '请仅填充 putOnSaleStartDate 和 putOnSaleEndDate。'
        }
        instruction = format_instructions.get(agent_type, '')

        prompt = f"""
        你是一个时间参数提取器。
        当前日期: {current_date}
        
        任务：根据 [用户查询]，提取时间范围参数。
        
        特定要求: {instruction}
        对于不需要的字段，请保持为 null。
        
        规则：
        1. **必须基于当前日期**计算相对时间（如“最近30天”）。
        2. 如果用户未提及时间，默认提取“最近30天”。
        
        [用户查询]: {current_query}
        """

        try:
            response = await llm_client.chat.completions.create(
                model=FAST_LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                # [关键更新] 使用 strict json_schema
                extra_body={
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "time_result",
                            "schema": TimeResult.model_json_schema(),
                            "strict": True
                        }
                    }
                },
                temperature=0.0
            )
            
            content = response.choices[0].message.content
            result_obj = TimeResult.model_validate_json(content)
            
            # 转为字典并剔除 None 值
            time_params = result_obj.model_dump(exclude_none=True)
            
            final_params = cached_params.copy()
            final_params.update(time_params)
            
            print(f"⏰ [Time Calibrated] {agent_type}: {time_params}")
            return final_params
            
        except Exception as e:
            print(f"⚠️ Time Calibration Error: {e}")
            return cached_params