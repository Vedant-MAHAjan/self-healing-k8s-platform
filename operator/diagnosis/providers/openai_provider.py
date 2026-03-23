"""
OpenAI provider for AI diagnosis.
"""

import structlog
from openai import AsyncOpenAI
from typing import Optional

from healing_operator.diagnosis.prompts import build_chat_messages


logger = structlog.get_logger()


class OpenAIProvider:
    """OpenAI LLM provider for diagnosis."""
    
    def __init__(self, api_key: str, model: str, timeout: int = 30):
        self.model = model
        self.timeout = timeout
        self.client = AsyncOpenAI(
            api_key=api_key,
            timeout=timeout,
        )
        logger.info("openai_provider_initialized", model=model)
    
    async def complete(self, prompt: str) -> str:
        """
        Get a completion from OpenAI.
        
        Args:
            prompt: The prompt to send
            
        Returns:
            The completion text
        """
        from healing_operator.models import Issue
        
        try:
            # For structured diagnosis, we'll use function calling
            # to ensure JSON response
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert Kubernetes SRE. Diagnose issues and respond in JSON format with:
{
  "root_cause": "brief cause",
  "analysis": "detailed analysis",
  "recommended_strategy": "restart_pod|scale_up|rollback_deployment|increase_resources|manual_intervention|no_action",
  "confidence": 0.0-1.0,
  "reasoning": "explanation",
  "alternative_strategies": [],
  "requires_manual_intervention": false,
  "suggested_actions": []
}"""
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,  # Lower temperature for more consistent analysis
                response_format={"type": "json_object"},  # Ensure JSON response
            )
            
            content = response.choices[0].message.content
            
            logger.debug(
                "openai_completion_received",
                model=self.model,
                tokens_used=response.usage.total_tokens,
            )
            
            return content
        
        except Exception as e:
            logger.error(
                "openai_completion_failed",
                error=str(e),
                exc_info=True,
            )
            raise
    
    async def cleanup(self):
        """Cleanup resources."""
        await self.client.close()
        logger.info("openai_provider_cleanup_complete")
