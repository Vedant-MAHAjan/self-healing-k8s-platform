"""
Ollama LLM provider for AI diagnosis.
Uses local Ollama for FREE AI inference - no API keys required!

Supports models like:
- llama3
- mistral  
- deepseek-coder
- codellama
"""

import json
import structlog
import aiohttp
from typing import Optional

from healing_operator.diagnosis.prompts import DIAGNOSIS_SYSTEM_PROMPT


logger = structlog.get_logger()


class OllamaProvider:
    """
    Ollama local LLM provider for diagnosis.
    
    FREE, runs locally, no API keys needed!
    Install: https://ollama.ai
    """
    
    def __init__(
        self,
        model: str = "llama3",
        host: str = "http://localhost:11434",
        timeout: int = 60,
    ):
        self.model = model
        self.host = host
        self.timeout = timeout
        logger.info("ollama_provider_initialized", model=model, host=host)
    
    async def complete(self, prompt: str) -> str:
        """
        Get a completion from Ollama.
        
        Args:
            prompt: The prompt to send
            
        Returns:
            The completion text
        """
        try:
            url = f"{self.host}/api/chat"
            
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": DIAGNOSIS_SYSTEM_PROMPT
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                "stream": False,
                "format": "json",  # Request JSON output
                "options": {
                    "temperature": 0.3,
                    "num_predict": 1000,
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"Ollama error: {error_text}")
                    
                    result = await response.json()
                    content = result.get("message", {}).get("content", "")
                    
                    logger.debug(
                        "ollama_completion_received",
                        model=self.model,
                        response_length=len(content),
                    )
                    
                    return content
        
        except aiohttp.ClientError as e:
            logger.error(
                "ollama_connection_failed",
                error=str(e),
                hint="Is Ollama running? Start with: ollama serve",
            )
            raise
        
        except Exception as e:
            logger.error(
                "ollama_completion_failed",
                error=str(e),
                exc_info=True,
            )
            raise
    
    async def check_health(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            async with aiohttp.ClientSession() as session:
                # Check Ollama is running
                async with session.get(f"{self.host}/api/tags") as response:
                    if response.status != 200:
                        return False
                    
                    data = await response.json()
                    models = [m.get("name", "").split(":")[0] for m in data.get("models", [])]
                    
                    if self.model not in models and f"{self.model}:latest" not in [m.get("name") for m in data.get("models", [])]:
                        logger.warning(
                            "ollama_model_not_found",
                            model=self.model,
                            available=models,
                            hint=f"Pull model with: ollama pull {self.model}",
                        )
                        return False
                    
                    return True
        except Exception as e:
            logger.error("ollama_health_check_failed", error=str(e))
            return False
    
    async def cleanup(self):
        """Cleanup resources (no-op for Ollama)."""
        logger.info("ollama_provider_cleanup_complete")
