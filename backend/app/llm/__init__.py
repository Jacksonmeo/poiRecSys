"""LLM 客户端层（Stage 4）。

抽象 LLMClient，支持 OpenAI 兼容 API，不绑定单一模型。
providers/ 目录存放具体实现（mock 为规则路由模拟，openai_compat 为真实 API）。
"""
