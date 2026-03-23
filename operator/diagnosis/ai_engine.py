"""
AI-powered diagnosis engine for Kubernetes issues.

Supports multiple providers:
- ollama: LOCAL LLM via Ollama (FREE, RECOMMENDED for demo!)
- mock: Smart rule-based simulation (fallback, no setup needed)
- openai: OpenAI GPT-4 (requires API key, optional)
- anthropic: Anthropic Claude (requires API key, optional)

For the demo, we recommend using Ollama for REAL AI at zero cost!
Install: https://ollama.ai
Run: ollama pull llama3 && ollama serve
"""

import json
import structlog
from datetime import datetime
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from healing_operator.config import Settings
from healing_operator.models import Issue, Diagnosis, RemediationStrategy
from healing_operator.diagnosis.providers.mock_provider import MockAIProvider
from healing_operator.diagnosis.prompts import build_diagnosis_prompt


logger = structlog.get_logger()


class AIEngine:
    """
    AI-powered diagnosis engine that analyzes Kubernetes issues
    and recommends remediation strategies.
    
    Providers (in order of recommendation for demo):
    1. ollama - Real AI, runs locally, FREE
    2. mock - Smart rule-based, no setup needed
    3. openai/anthropic - Paid APIs (optional)
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize the AI provider."""
        if self._initialized:
            return
        
        provider_name = self.settings.ai_provider.lower()
        
        # RECOMMENDED: Ollama - Real AI, runs locally, FREE!
        if provider_name == 'ollama':
            from healing_operator.diagnosis.providers.ollama_provider import OllamaProvider
            self.provider = OllamaProvider(
                model=self.settings.ollama_model,
                host=self.settings.ollama_host,
                timeout=self.settings.ai_timeout,
            )
            
            # Check if Ollama is running
            if await self.provider.check_health():
                logger.info(
                    "ai_engine_initialized",
                    provider="ollama",
                    model=self.settings.ollama_model,
                    message="Using LOCAL LLM - real AI, zero cost!"
                )
            else:
                logger.warning(
                    "ollama_not_available",
                    hint="Start Ollama with: ollama serve && ollama pull llama3",
                    fallback="Using mock provider instead"
                )
                self.provider = MockAIProvider()
        
        # FALLBACK: Mock provider - smart rules, no setup
        elif provider_name == 'mock':
            self.provider = MockAIProvider()
            logger.info(
                "ai_engine_initialized",
                provider="mock",
                message="Using smart rule-based diagnosis"
            )
        
        elif provider_name == 'openai':
            # Optional: Real OpenAI integration
            if not self.settings.openai_api_key:
                logger.warning("OpenAI key not set, falling back to mock provider")
                self.provider = MockAIProvider()
            else:
                from healing_operator.diagnosis.providers.openai_provider import OpenAIProvider
                self.provider = OpenAIProvider(
                    api_key=self.settings.openai_api_key,
                    model=self.settings.openai_model,
                    timeout=self.settings.ai_timeout,
                )
        
        elif provider_name == 'anthropic':
            # Optional: Real Anthropic integration
            if not self.settings.anthropic_api_key:
                logger.warning("Anthropic key not set, falling back to mock provider")
                self.provider = MockAIProvider()
            else:
                from healing_operator.diagnosis.providers.anthropic_provider import AnthropicProvider
                self.provider = AnthropicProvider(
                    api_key=self.settings.anthropic_api_key,
                    model=self.settings.anthropic_model,
                    timeout=self.settings.ai_timeout,
                )
        
        else:
            # Unknown provider, use mock
            logger.warning(f"Unknown provider '{provider_name}', using mock")
            self.provider = MockAIProvider()
        
        self._initialized = True
    
    async def cleanup(self):
        """Cleanup resources."""
        if self.provider:
            await self.provider.cleanup()
        logger.info("ai_engine_cleanup_complete")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def diagnose(self, issue: Issue) -> Diagnosis:
        """
        Diagnose an issue using AI and recommend a remediation strategy.
        
        Args:
            issue: The detected issue to diagnose
            
        Returns:
            Diagnosis with recommended remediation strategy
        """
        if not self._initialized:
            await self.initialize()
        
        logger.info(
            "ai_diagnosis_started",
            issue_id=issue.issue_id,
            issue_type=issue.issue_type.value,
        )
        
        start_time = datetime.utcnow()
        
        try:
            # Build the prompt
            prompt = build_diagnosis_prompt(issue)
            
            # Get AI response - mock provider needs the issue for context
            if isinstance(self.provider, MockAIProvider):
                response = await self.provider.complete(prompt, issue)
            else:
                response = await self.provider.complete(prompt)
            
            # Parse the response
            diagnosis = self._parse_diagnosis(issue, response)
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            logger.info(
                "ai_diagnosis_completed",
                issue_id=issue.issue_id,
                strategy=diagnosis.recommended_strategy.value,
                confidence=diagnosis.confidence,
                duration_seconds=duration,
            )
            
            return diagnosis
        
        except Exception as e:
            logger.error(
                "ai_diagnosis_failed",
                issue_id=issue.issue_id,
                error=str(e),
                exc_info=True,
            )
            
            # Fallback to rule-based diagnosis
            return self._fallback_diagnosis(issue)
    
    def _parse_diagnosis(self, issue: Issue, response: str) -> Diagnosis:
        """
        Parse the AI response into a Diagnosis object.
        
        Expected JSON response format:
        {
            "root_cause": "...",
            "analysis": "...",
            "recommended_strategy": "restart_pod",
            "confidence": 0.85,
            "reasoning": "...",
            "alternative_strategies": ["scale_up"],
            "requires_manual_intervention": false,
            "suggested_actions": ["..."]
        }
        """
        try:
            # Try to parse as JSON
            data = json.loads(response)
            
            # Map strategy string to enum
            strategy_str = data.get('recommended_strategy', 'no_action')
            try:
                recommended_strategy = RemediationStrategy(strategy_str)
            except ValueError:
                logger.warning(
                    "invalid_strategy_in_response",
                    strategy=strategy_str,
                )
                recommended_strategy = RemediationStrategy.NO_ACTION
            
            # Parse alternative strategies
            alternative_strategies = []
            for alt_str in data.get('alternative_strategies', []):
                try:
                    alternative_strategies.append(RemediationStrategy(alt_str))
                except ValueError:
                    pass
            
            return Diagnosis(
                issue=issue,
                root_cause=data.get('root_cause', 'Unknown'),
                analysis=data.get('analysis', ''),
                recommended_strategy=recommended_strategy,
                confidence=float(data.get('confidence', 0.5)),
                reasoning=data.get('reasoning', ''),
                alternative_strategies=alternative_strategies,
                requires_manual_intervention=data.get('requires_manual_intervention', False),
                suggested_actions=data.get('suggested_actions', []),
            )
        
        except json.JSONDecodeError:
            # If not valid JSON, try to extract information from text
            logger.warning("ai_response_not_json", response=response[:200])
            return self._parse_text_diagnosis(issue, response)
    
    def _parse_text_diagnosis(self, issue: Issue, response: str) -> Diagnosis:
        """Parse a text-based diagnosis response."""
        # Simple heuristic-based parsing
        response_lower = response.lower()
        
        # Determine strategy based on keywords
        if 'restart' in response_lower:
            strategy = RemediationStrategy.RESTART_POD
        elif 'scale up' in response_lower or 'increase replicas' in response_lower:
            strategy = RemediationStrategy.SCALE_UP
        elif 'rollback' in response_lower or 'revert' in response_lower:
            strategy = RemediationStrategy.ROLLBACK_DEPLOYMENT
        elif 'increase resources' in response_lower or 'more memory' in response_lower:
            strategy = RemediationStrategy.INCREASE_RESOURCES
        else:
            strategy = RemediationStrategy.MANUAL_INTERVENTION
        
        return Diagnosis(
            issue=issue,
            root_cause="Analysis from AI (text format)",
            analysis=response,
            recommended_strategy=strategy,
            confidence=0.6,  # Lower confidence for text parsing
            reasoning="Parsed from text response",
        )
    
    def _fallback_diagnosis(self, issue: Issue) -> Diagnosis:
        """
        Provide a rule-based diagnosis when AI fails.
        Simple heuristics based on issue type.
        """
        logger.info(
            "using_fallback_diagnosis",
            issue_id=issue.issue_id,
            issue_type=issue.issue_type.value,
        )
        
        strategy_map = {
            'CrashLoopBackOff': RemediationStrategy.RESTART_POD,
            'ImagePullBackOff': RemediationStrategy.ROLLBACK_DEPLOYMENT,
            'OOMKilled': RemediationStrategy.INCREASE_RESOURCES,
            'MemoryLeak': RemediationStrategy.RESTART_POD,
            'HealthCheckFailure': RemediationStrategy.RESTART_POD,
            'PodPending': RemediationStrategy.MANUAL_INTERVENTION,
        }
        
        strategy = strategy_map.get(
            issue.issue_type.value,
            RemediationStrategy.NO_ACTION
        )
        
        return Diagnosis(
            issue=issue,
            root_cause=f"Rule-based analysis: {issue.issue_type.value}",
            analysis=f"Fallback diagnosis for {issue.description}",
            recommended_strategy=strategy,
            confidence=0.5,  # Lower confidence for fallback
            reasoning="AI diagnosis unavailable, using rule-based approach",
            requires_manual_intervention=(strategy == RemediationStrategy.MANUAL_INTERVENTION),
        )
