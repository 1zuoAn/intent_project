# intent_project/services/cache_service.py
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4

from openai import AsyncOpenAI
from flowllm.core.vector_store.es_vector_store import EsVectorStore
from flowllm.core.schema import VectorNode

from intent_project.core.config import settings
from intent_project.schemas.base import (
    CacheCheckResponse, AgentType, JudgeResult, TimeResult
)

class CacheService:
    def __init__(self, vector_store: EsVectorStore, llm_client: AsyncOpenAI):
        """
        依赖注入: 也就是“你要用什么工具，我传给你，而不是你自己去买”。
        """
        self.vs = vector_store
        self.llm_client = llm_client
        self.workspace_id = settings.CACHE_WORKSPACE_ID
        # 缓存判定用的小模型，速度快
        self.fast_model = settings.REAL_LLM_MODEL 

    def _construct_vector_key(self, query: str, preferred_entity: Optional[str], history: Optional[str]) -> str:
        """构建向量索引 Key"""
        entity_str = preferred_entity if preferred_entity else "无偏好"
        history_str = history[-500:] if history else "无历史记录"
        return f"用户当前查询: {query}；偏好平台: {entity_str}；对话历史摘要: {history_str}"

    async def check_cache(self, query: str, history: str = "", preferred_entity: str = None) -> CacheCheckResponse:
        """核心流程：检索 -> 分级判定 -> 时间校准"""
        search_text = self._construct_vector_key(query, preferred_entity, history)

        # 向量检索 (依赖之前的 Patch)
        results = await self.vs.async_search(
            workspace_id=self.workspace_id,
            query=search_text,
            top_k=1 
        )

        if not results:
            return CacheCheckResponse(hit=False, reason="Tier 3: No results found", score=0.0)

        best_match = results[0]
        score = best_match.metadata.get("_score", 0.0)
        
        # 初筛
        if score < 0.90:
             return CacheCheckResponse(hit=False, reason="Tier 3: Low similarity (<0.90)", score=score)
        
        try:
            # 兼容处理：有些 metadata 可能是字符串，有些是字典
            payload_raw = best_match.metadata.get("cached_payload_json")
            if isinstance(payload_raw, str):
                cached_data = json.loads(payload_raw)
            else:
                cached_data = payload_raw

            cached_params = cached_data["api_params"]
            cached_agent_type = cached_data["agent_type"]
            cached_query = cached_data["original_query"]
        except Exception as e:
            return CacheCheckResponse(hit=False, reason=f"Cache Data Corrupted: {e}", score=score)

        print(f"🔍 [Cache Search] Score: {score:.4f} | Agent: {cached_agent_type}")

        # --- Tier 1: 完美匹配 ---
        if score >= 0.99:
            final_params = await self._calibrate_time(query, cached_agent_type, cached_params)
            return CacheCheckResponse(
                hit=True, 
                agent_type=cached_agent_type, 
                final_params=final_params, 
                reason="Tier 1: Exact Match", 
                score=score
            )

        # --- Tier 2: 高度相似 (LLM 裁判) ---
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
            return CacheCheckResponse(hit=False, reason="Tier 2: Judge Rejected", score=score)

    async def save_execution(self, query: str, history: str, preferred_entity: str, agent_type: str, params: Dict[str, Any]):
        """保存执行结果到缓存"""
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
            emb = self.vs.embedding_model.get_embeddings([vector_text])
            if emb:
                node.vector = emb[0]

        await self.vs.async_insert(nodes=[node], workspace_id=self.workspace_id)
        print(f"💾 [Cache Saved] {agent_type}: {query[:20]}...")

    # ================= LLM 逻辑 =================

    async def _llm_judge(self, current_query: str, cached_query: str, cached_params: Dict, current_entity: str) -> bool:
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
        
        如果除了时间以外的任何条件（不仅仅上述绝对禁止差异部分，其他处时间外任何属性的差异）有偏差，必须返回 false。
        """
        
        try:
            response = await self.llm_client.chat.completions.create(
                model=self.fast_model,
                messages=[{"role": "user", "content": prompt}],
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
            result = JudgeResult.model_validate_json(content)
            return result.reusable
        except Exception as e:
            print(f"⚠️ Judge Error: {e}")
            return False

    async def _calibrate_time(self, current_query: str, agent_type: str, cached_params: Dict) -> Dict:
        """
        [修改] 时间校准：通用提取 -> 特定字段映射
        """
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # 1. 通用 Prompt：只让 LLM 提取标准开始/结束时间
        prompt = f"""
        你是一个时间参数提取器。
        当前日期: {current_date}
        
        任务：根据用户查询，提取时间范围。
        规则：
        1. 必须基于当前日期计算相对时间（如“最近30天”）。
        2. 如果用户未提及时间，默认提取“最近30天”。
        3. 格式必须为 YYYY-MM-DD。
        
        [用户查询]: {current_query}
        """

        try:
            # 2. 调用 LLM 提取通用时间结构
            response = await self.llm_client.chat.completions.create(
                model=self.fast_model,
                messages=[{"role": "user", "content": prompt}],
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
            time_res = TimeResult.model_validate_json(content)
            
            # 3. [关键] 根据 agent_type 映射到不同的字段名
            final_params = cached_params.copy()
            
            if agent_type == "douyi":
                # 抖衣接口字段
                final_params["sortStartDate"] = time_res.start_date
                final_params["sortEndDate"] = time_res.end_date
                # 清理旧时间字段(如果有)
                final_params.pop("dateRange", None) 
                
            elif agent_type == "abroad":
                # 海外接口字段
                final_params["putOnSaleStartDate"] = time_res.start_date
                final_params["putOnSaleEndDate"] = time_res.end_date
                
            elif agent_type == "zhiyi":
                # 知衣接口字段
                final_params["startTime"] = time_res.start_date
                final_params["endTime"] = time_res.end_date
            
            print(f"⏰ [Time Calibrated] {agent_type}: {time_res.start_date} ~ {time_res.end_date}")
            return final_params
            
        except Exception as e:
            print(f"⚠️ Time Calibration Error: {e}")
            return cached_params
    async def list_cache_entries(self, limit: int = 50) -> List[Dict]:
        """
        列出当前的缓存条目，并解析 metadata 中的 JSON 字符串
        """
        # 1. 强制刷新索引，确保能查到最新写入的数据
        try:
            if hasattr(self.vs, "_async_client"):
                await self.vs._async_client.indices.refresh(index=self.workspace_id)
        except Exception:
            pass

        # 2. 使用 Patch 过的列表查询方法
        nodes = await self.vs.async_list_workspace_nodes(workspace_id=self.workspace_id, max_size=limit)
        
        results = []
        for node in nodes:
            # 提取基础信息
            item = {
                "id": node.unique_id,
                "score": node.metadata.get("_score", 0.0), # 如果是搜索出来的会有分
                "vector_key": node.content, # 当时的构造 Key
            }
            
            # 智能解析 metadata (原本存的是字符串，现在还原为对象)
            raw_meta = node.metadata
            if "cached_payload_json" in raw_meta:
                try:
                    payload = json.loads(raw_meta["cached_payload_json"])
                    item.update(payload) # 展开显示 agent_type, original_query, api_params
                except:
                    item["raw_payload"] = raw_meta["cached_payload_json"]
            else:
                item["metadata"] = raw_meta
            
            results.append(item)
            
        return results

    async def delete_cache_entry(self, unique_id: str) -> bool:
        """
        删除指定的缓存条目
        """
        try:
            # EsVectorStore 的删除通常需要列表
            await self.vs.async_delete(ids=[unique_id], workspace_id=self.workspace_id)
            return True
        except Exception as e:
            print(f"⚠️ Delete Cache Failed: {e}")
            # 如果是用 client 直连删除 (备选方案，防止 flowllm 接口差异)
            if hasattr(self.vs, "_async_client"):
                try:
                    await self.vs._async_client.delete(index=self.workspace_id, id=unique_id)
                    return True
                except Exception as inner_e:
                    print(f"⚠️ Direct Delete Failed: {inner_e}")
            return False

    async def flush_all_cache(self) -> bool:
        """
        [危险] 清空所有缓存
        """
        try:
            await self.vs.async_delete_workspace(self.workspace_id)
            await self.vs.async_create_workspace(self.workspace_id)
            return True
        except Exception as e:
            print(f"❌ Flush Cache Failed: {e}")
            return False