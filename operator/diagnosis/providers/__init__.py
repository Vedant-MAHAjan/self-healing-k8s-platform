"""AI provider implementations.

Available providers:
- OllamaProvider: FREE local LLM (recommended for demo)
- MockAIProvider: Smart rule-based fallback (no setup needed)
- OpenAIProvider: OpenAI GPT-4 (requires API key)
- AnthropicProvider: Anthropic Claude (requires API key)
"""

__all__ = ['OllamaProvider', 'MockAIProvider', 'OpenAIProvider', 'AnthropicProvider']
