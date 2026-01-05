import json
from datetime import datetime, timedelta
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
# 定义各接口发给 LLM 裁判的“可读参数白名单”
# 没在名单里的 ID 字段（如 rootCategoryId, team_id）会被自动过滤
JUDGE_WHITELIST = {
    "douyi": [
        "keyword", "propertyList", "sortField", "sortType", 
        "minPrice", "maxPrice", "isMonitorShop", "isMonitorStreamer"
    ],
    "zhiyi": [
        "keywords", "sort", "filters", "platform", 
        "minPrice", "maxPrice"
    ],
    "abroad": [
        "keyword", "brand", "site", "platform", 
        "countryList", "minSprice", "maxSprice", "minSaleVolumeTotal"
    ]
}
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

    def _filter_readable_params(self, params: Dict, agent_type: str) -> Dict:
        """
        [新增] 参数清洗：只保留 LLM 能读懂的业务字段，过滤掉 ID 类黑盒参数
        """
        whitelist = JUDGE_WHITELIST.get(agent_type, [])
        if not whitelist:
            # 兜底：过滤掉 obvious 的 ID 字段
            return {
                k: v for k, v in params.items() 
                if not k.lower().endswith("id") and "list" not in k.lower()
            }
        # 只提取白名单内的字段
        return {k: params[k] for k in whitelist if k in params}

    async def _llm_judge(self, current_query: str, cached_query: str, cached_params: Dict, agent_type: str, current_entity: str) -> bool:
        """
        [优化版] 裁判：根据不同 Agent 类型，加载特定的校验清单。
        """
        
        # 1. 参数清洗：过滤 ID，只留语义字段
        readable_params = self._filter_readable_params(cached_params, agent_type)

        # 2. 定义不同 Agent 的“死刑清单”
        checklists = {
            "douyi": """
            【抖衣-重点比对字段】
            1. **核心语义**: keyword (搜索词) 必须在语义上一致。
            2. **多属性列表 (propertyList)**: 这是最关键的！必须检查 reference_params['propertyList'] 里的每一个属性（如材质、风格、领型、适用季节）。
               - 例子: 如果缓存是"夏季"，当前搜"冬季" -> 拒绝。
               - 例子: 如果缓存是"法式风格"，当前搜"新中式" -> 拒绝。
            3. **监控设置**: isMonitorShop (搜店铺), isMonitorStreamer (搜达人) 的状态必须一致。
            4. **排序**: sortField (排序字段) 和 sortType 必须一致。
            5. **价格**: minPrice, maxPrice 必须一致。
            """,
            
            "zhiyi": """
            【知衣-重点比对字段】
            1. **过滤条件 (filters)**: 这是核心！必须检查 reference_params['filters'] 数组。
               - 必须确保所有的筛选标签（材质、风格、工艺等）都与当前意图完全匹配。
            2. **排序**: sort 字段必须一致。
            3. **平台**: platform 必须一致 (如淘宝 vs 天猫)。
            4. **价格**: minPrice, maxPrice 必须一致。
            """,
            
            "abroad": """
            【海外探款-重点比对字段】
            1. **站点/国家**: site, platform, countryList 必须严格一致。
            2. **品牌**: brand 字段必须一致。
            3. **价格与销量**: minSprice/maxSprice, minSaleVolumeTotal 等区间必须一致。
            """
        }

        # 获取当前 Agent 的特定规则
        specific_checklist = checklists.get(agent_type, "请严格比对所有非时间类的业务参数。")

        prompt = f"""
        你是一个极其严格的参数复用裁判。
        任务：判断【当前意图】是否可以完全复用【历史意图】的参数模板（仅允许时间不同）。

        --------------------------------------------------
        [上下文信息]
        - Agent 类型: {agent_type}
        - 历史查询: {cached_query}
        - 参考参数 (JSON): {json.dumps(readable_params, ensure_ascii=False)}
        - 当前查询: {current_query}
        - 当前偏好: {current_entity if current_entity else "无"}
        --------------------------------------------------

        [你的校验清单]
        {specific_checklist}

        [通用判决公理] (最高优先级)
        1. **唯一允许的差异**: 仅允许“时间”、“日期”、“最近多少天”、“年份季节(如24春夏 vs 24秋冬)”这种【时间维度】的差异。
           - 注意：如果是“24春夏”变“24秋冬”，虽然带有季节词，但本质是时间窗的平移，通常属于允许范围。但如果涉及具体的“季节属性标签”（如适合夏天穿的），则属于属性冲突。请结合上下文判断，如果是选品周期变化则允许。
        2. **零容忍原则**: 
           - 如果参考参数中包含具体的属性列表（如 propertyList, filters），而当前查询意图改变了其中的任何一项（例如换了颜色、换了材质、换了风格），**必须返回 false**。
           - 此时我们无法得知属性列表中具体存放了什么，所以只要你感觉到除了时间以外的意图有任何细微偏差，**直接返回 false** 作为保底。不要尝试“模糊匹配”。

        --------------------------------------------------
        请输出 JSON 格式: {{ "reusable": boolean, "reason": "string" }}
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
            
            if not result.reusable:
                print(f"🚫 [Judge] Rejected ({agent_type}): {result.reason}")
            else:
                print(f"✅ [Judge] Approved ({agent_type})")

            return result.reusable
        except Exception as e:
            print(f"⚠️ Judge Error: {e}")
            return False

    def _apply_date_offset(self, date_str: str, offset_days: int) -> str:
        """
        将 YYYY-MM-DD 字符串偏移指定天数
        """
        try:
            if not date_str:
                return date_str
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            new_dt = dt + timedelta(days=offset_days)
            return new_dt.strftime("%Y-%m-%d")
        except Exception:
            # 如果解析失败（防呆），原样返回
            return date_str

    async def _calibrate_time(self, current_query: str, agent_type: str, cached_params: Dict) -> Dict:
        """
        [修改] 时间校准：LLM 提取标准时间 -> 代码层根据业务规则偏移
        """
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        # 1. 保持 Prompt 干净，只让 LLM 提取基于"今天"的标准时间
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
            # 2. LLM 提取标准时间
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
            
            # 3. [新增] 业务规则偏移逻辑 (Post-Processing)
            # 定义各平台的延迟天数 (负数表示向前推)
            offset_days = 0
            if agent_type == "zhiyi":
                offset_days = -2
            elif agent_type in ["douyi", "abroad"]:
                offset_days = -1
            
            # 执行偏移
            final_start = self._apply_date_offset(time_res.start_date, offset_days)
            final_end = self._apply_date_offset(time_res.end_date, offset_days)

            # 4. 字段映射 (同时填入偏移后的时间)
            final_params = cached_params.copy()
            
            if agent_type == "douyi":
                final_params["sortStartDate"] = final_start
                final_params["sortEndDate"] = final_end
                final_params.pop("dateRange", None) 
                
            elif agent_type == "abroad":
                final_params["putOnSaleStartDate"] = final_start
                final_params["putOnSaleEndDate"] = final_end
                
            elif agent_type == "zhiyi":
                final_params["startTime"] = final_start
                final_params["endTime"] = final_end
            
            print(f"⏰ [Time Calibrated] {agent_type} (Offset {offset_days}d): {final_start} ~ {final_end}")
            return final_params
            
        except Exception as e:
            print(f"⚠️ Time Calibration Error: {e}")
            return cached_params