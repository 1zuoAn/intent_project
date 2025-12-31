# intent_project/services/intent_service.py
import json
from typing import List, Optional
from openai import AsyncOpenAI
from pydantic import ValidationError

from intent_project.core.config import settings
from intent_project.core.prompts import N8N_SYSTEM_PROMPT_TEMPLATE
from intent_project.schemas.base import (
    ClassifyResult, IntentEnum, CLASSIFY_JSON_SCHEMA
)

class LLMService:
    def __init__(self, client: AsyncOpenAI):
        self.client = client
        # 回退模型链
        self.models = [
            settings.REAL_LLM_MODEL,
            "google/gemini-2.0-flash-001", 
            "x-ai/grok-2-1212"
        ]

    async def classify_intent(
        self, 
        query: str, 
        history: Optional[str] = None, 
        preferred_entity: Optional[str] = None,
        memory_context: str = ""
    ) -> ClassifyResult:
        """
        核心分类逻辑
        :param memory_context: 外部检索到的记忆上下文，作为字符串传入
        """
        # 1. 准备 Prompt
        display_context = memory_context if memory_context else "暂无相关历史经验"
        system_prompt = N8N_SYSTEM_PROMPT_TEMPLATE.format(memory_context=display_context)
        
        formatted_history = history if history else "No History"
        user_input = f"""
<user_context>
        <preferred_entity_selection>
            {preferred_entity or "None (User did not select)"}
        </preferred_entity_selection>
        <conversation_history>
            {formatted_history}
        </conversation_history>
    </user_context>
    <current_query>
        {query}
    </current_query>
    <instruction>
        Please classify the intent of the content in <current_query>.
        Note: If the intent in <current_query> conflicts with <preferred_entity_selection>, trust the explicit intent in <current_query>.
    </instruction>
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]

        # 2. 执行带重试的调用
        return await self._call_with_retry(messages)

    async def _call_with_retry(self, messages: List[dict]) -> ClassifyResult:
        last_exception = None
        
        # 简单的模型去重
        unique_models = []
        seen = set()
        for m in self.models:
            if m and m not in seen:
                unique_models.append(m)
                seen.add(m)

        for model_name in unique_models:
            print(f"🤖 [Classify] Trying model: {model_name}...")
            try:
                completion = await self.client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    timeout=30,
                    extra_body={
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": CLASSIFY_JSON_SCHEMA
                        }
                    }
                )
                
                content = completion.choices[0].message.content.strip()
                # 兼容性清洗
                if content.startswith("```"):
                    content = content.replace("```json", "").replace("```", "").strip()
                
                return ClassifyResult.model_validate_json(content)
                
            except Exception as e:
                print(f"⚠️ Model {model_name} failed: {e}")
                last_exception = e
                continue
        
        # 如果全部失败，返回默认兜底
        print(f"🔥 All models failed. Fallback to CHATBOT. Error: {last_exception}")
        return ClassifyResult(
            category=IntentEnum.CHATBOT,
            reasoning=f"System Error: {str(last_exception)}"
        )