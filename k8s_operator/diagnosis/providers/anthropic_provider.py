"""
Anthropic Claude provider for AI diagnosis.
"""

import json
import structlog
from anthropic import AsyncAnthropic
from typing import Optional

from ..prompts import DIAGNOSIS_SYSTEM_PROMPT


logger = structlog.get_logger()


class AnthropicProvider:
    """Anthropic Claude LLM provider for diagnosis."""
    
    def __init__(self, api_key: str, model: str, timeout: int = 30):
        self.model = model
        self.timeout = timeout
        self.client = AsyncAnthropic(
            api_key=api_key,
            timeout=timeout,
        )
        logger.info("anthropic_provider_initialized", model=model)
    
    async def complete(self, prompt: str) -> str:
        """
        Get a completion from Anthropic Claude.
        
        Args:
            prompt: The prompt to send
            
        Returns:
            The completion text
        """
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                temperature=0.3,
                system=DIAGNOSIS_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            
            content = response.content[0].text
            
            logger.debug(
                "anthropic_completion_received",
                model=self.model,
                tokens_used=response.usage.input_tokens + response.usage.output_tokens,
            )
            
            return content
        
        except Exception as e:
            logger.error(
                "anthropic_completion_failed",
                error=str(e),
                exc_info=True,
            )
            raise
    
    async def cleanup(self):
        """Cleanup resources."""
        await self.client.close()
        logger.info("anthropic_provider_cleanup_complete")
