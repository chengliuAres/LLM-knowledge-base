"""LLM 客户端封装 - 支持多种后端"""

import os
from typing import AsyncGenerator, Union


# 小米 MiMo 配置
XIAOMI_API_KEY = "tp-cjdh66icm8h140rcvvlffq0pmyszd8im1u0hjkdo0rsdvrxi"
XIAOMI_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
XIAOMI_MODEL = "mimo-v2.5-pro"


class LLMClient:
    """LLM 客户端基类"""
    
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.model = model or os.getenv("LLM_MODEL", "gpt-3.5-turbo")
    
    async def chat(self, messages: list, stream: bool = False) -> Union[str, AsyncGenerator]:
        """发送聊天请求"""
        raise NotImplementedError


class OpenAICompatibleClient(LLMClient):
    """OpenAI 兼容客户端（支持 OpenAI、DeepSeek、小米MiMo、Ollama 等）"""
    
    async def chat(self, messages: list, stream: bool = False):
        from openai import AsyncOpenAI
        
        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
        if stream:
            return self._stream_chat(client, messages)
        else:
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=2000
            )
            return response.choices[0].message.content
    
    async def _stream_chat(self, client, messages: list) -> AsyncGenerator:
        """流式输出"""
        stream = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=2000,
            stream=True
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端实例"""
    # 优先使用环境变量配置
    provider = os.getenv("LLM_PROVIDER", "xiaomi")
    
    if provider == "ollama":
        # 本地 Ollama
        return OpenAICompatibleClient(
            api_key="ollama",
            base_url="http://localhost:11434/v1",
            model=os.getenv("LLM_MODEL", "qwen2:7b")
        )
    elif provider == "xiaomi":
        # 小米 MiMo
        return OpenAICompatibleClient(
            api_key=XIAOMI_API_KEY,
            base_url=XIAOMI_BASE_URL,
            model=XIAOMI_MODEL
        )
    else:
        # OpenAI 兼容接口（从环境变量读取）
        return OpenAICompatibleClient()


def build_rag_prompt(query: str, context: str) -> list:
    """构建 RAG 提示词"""
    system_prompt = """你是一个智能助手，基于提供的文档内容回答用户问题。

规则：
1. 只根据提供的文档内容回答，不要编造信息
2. 如果文档中没有相关信息，明确告知用户
3. 回答要简洁、准确、有条理
4. 可以适当引用文档原文，用引号标注"""

    user_prompt = f"""基于以下文档内容，回答用户的问题。

【文档内容】
{context}

【用户问题】
{query}

请给出准确、简洁的回答："""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
