"""
AlphaZero Capital - Multi-Provider LLM Abstraction
Supports: Claude, OpenAI GPT-4, Google Gemini, OpenRouter, Local Models

NEW: OpenRouter support - Access 100+ models through one API!
"""

import os
from typing import Dict, List, Optional
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """Base class for all LLM providers"""
    
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
    
    @abstractmethod
    def chat(self, prompt: str, **kwargs) -> str:
        """Send a chat message and get response"""
        pass
    
    @abstractmethod
    def chat_with_history(self, messages: List[Dict], **kwargs) -> str:
        """Chat with conversation history"""
        pass
    
    @abstractmethod
    def get_cost_estimate(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD"""
        pass


class OpenRouterProvider(BaseLLMProvider):
    """
    OpenRouter provider - Access 100+ models through one API!
    
    Supported models include:
    - Claude (Anthropic): claude-3-opus, claude-3-sonnet, claude-3-haiku
    - GPT-4 (OpenAI): gpt-4-turbo, gpt-4, gpt-3.5-turbo
    - Gemini (Google): gemini-pro, gemini-pro-vision
    - Llama (Meta): llama-3-70b, llama-3-8b
    - Mixtral (Mistral): mixtral-8x7b, mixtral-8x22b
    - And 100+ more!
    
    Pricing: Pay per token, varies by model
    See: https://openrouter.ai/models
    """
    
    def __init__(self, api_key: str, model: str = "anthropic/claude-3-sonnet"):
        super().__init__(api_key, model)
        
        try:
            from openai import OpenAI
            
            # OpenRouter uses OpenAI-compatible API
            self.client = OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1"
            )
            
            logger.info(f"OpenRouter provider initialized: {model}")
            logger.info(f"   Access to 100+ models through one API!")
            
        except ImportError:
            raise ImportError("Please install: pip install openai")
    
    def chat(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.7) -> str:
        """Send chat to OpenRouter"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "user", "content": prompt}
            ],
            # OpenRouter-specific headers
            extra_headers={
                "HTTP-Referer": "https://alphazero-capital.ai",  # Optional
                "X-Title": "AlphaZero Capital",  # Optional
            }
        )
        
        return response.choices[0].message.content
    
    def chat_with_history(
        self,
        messages: List[Dict],
        max_tokens: int = 4000,
        temperature: float = 0.7
    ) -> str:
        """Chat with history"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
            extra_headers={
                "HTTP-Referer": "https://alphazero-capital.ai",
                "X-Title": "AlphaZero Capital",
            }
        )
        
        return response.choices[0].message.content
    
    def get_cost_estimate(self, input_tokens: int, output_tokens: int) -> float:
        """
        Estimate cost for OpenRouter
        
        Costs vary by model:
        - Claude Sonnet: ~$3/1M input, ~$15/1M output
        - GPT-4 Turbo: ~$10/1M input, ~$30/1M output
        - Gemini Pro: ~$0.5/1M input, ~$1.5/1M output
        - Llama 3 70B: ~$0.9/1M input, ~$0.9/1M output
        
        See exact pricing: https://openrouter.ai/models
        """
        
        # Approximate costs (check OpenRouter for exact pricing)
        cost_map = {
            'anthropic/claude-3-opus': (15, 75),
            'anthropic/claude-3-sonnet': (3, 15),
            'anthropic/claude-3-haiku': (0.25, 1.25),
            'openai/gpt-4-turbo': (10, 30),
            'openai/gpt-4': (30, 60),
            'openai/gpt-3.5-turbo': (0.5, 1.5),
            'google/gemini-pro': (0.5, 1.5),
            'meta-llama/llama-3-70b': (0.9, 0.9),
            'mistralai/mixtral-8x7b': (0.7, 0.7),
        }
        
        # Get pricing for this model (default to Claude Sonnet pricing)
        input_price, output_price = cost_map.get(
            self.model, 
            (3, 15)  # Default to Claude Sonnet pricing
        )
        
        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        
        return input_cost + output_cost


class ClaudeProvider(BaseLLMProvider):
    """Anthropic Claude provider (direct API)"""
    
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        super().__init__(api_key, model)
        
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
            logger.info(f"Claude provider initialized: {model}")
        except ImportError:
            raise ImportError("Please install: pip install anthropic")
    
    def chat(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.7) -> str:
        """Send chat to Claude"""
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return response.content[0].text
    
    def chat_with_history(
        self, 
        messages: List[Dict], 
        max_tokens: int = 4000,
        temperature: float = 0.7
    ) -> str:
        """Chat with history"""
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages
        )
        
        return response.content[0].text
    
    def get_cost_estimate(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for Claude"""
        
        if 'opus' in self.model.lower():
            input_cost = (input_tokens / 1_000_000) * 15
            output_cost = (output_tokens / 1_000_000) * 75
        else:  # Sonnet
            input_cost = (input_tokens / 1_000_000) * 3
            output_cost = (output_tokens / 1_000_000) * 15
        
        return input_cost + output_cost


class OpenAIProvider(BaseLLMProvider):
    """OpenAI GPT provider (direct API)"""
    
    def __init__(self, api_key: str, model: str = "gpt-4-turbo"):
        super().__init__(api_key, model)
        
        try:
            import openai
            self.client = openai.OpenAI(api_key=api_key)
            logger.info(f"OpenAI provider initialized: {model}")
        except ImportError:
            raise ImportError("Please install: pip install openai")
    
    def chat(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.7) -> str:
        """Send chat to GPT"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return response.choices[0].message.content
    
    def chat_with_history(
        self,
        messages: List[Dict],
        max_tokens: int = 4000,
        temperature: float = 0.7
    ) -> str:
        """Chat with history"""
        
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages
        )
        
        return response.choices[0].message.content
    
    def get_cost_estimate(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for OpenAI"""
        
        if 'gpt-4' in self.model.lower():
            input_cost = (input_tokens / 1_000_000) * 10
            output_cost = (output_tokens / 1_000_000) * 30
        else:  # GPT-3.5
            input_cost = (input_tokens / 1_000_000) * 0.5
            output_cost = (output_tokens / 1_000_000) * 1.5
        
        return input_cost + output_cost


class GeminiProvider(BaseLLMProvider):
    """Google Gemini provider"""
    
    def __init__(self, api_key: str, model: str = "gemini-pro"):
        super().__init__(api_key, model)
        
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self.client = genai.GenerativeModel(model)
            logger.info(f"Gemini provider initialized: {model}")
        except ImportError:
            raise ImportError("Please install: pip install google-generativeai")
    
    def chat(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.7) -> str:
        """Send chat to Gemini"""
        
        generation_config = {
            'max_output_tokens': max_tokens,
            'temperature': temperature
        }
        
        response = self.client.generate_content(
            prompt,
            generation_config=generation_config
        )
        
        return response.text
    
    def chat_with_history(
        self,
        messages: List[Dict],
        max_tokens: int = 4000,
        temperature: float = 0.7
    ) -> str:
        """Chat with history"""
        
        chat = self.client.start_chat(history=[])
        
        for msg in messages[:-1]:
            if msg['role'] == 'user':
                chat.send_message(msg['content'])
        
        response = chat.send_message(
            messages[-1]['content'],
            generation_config={
                'max_output_tokens': max_tokens,
                'temperature': temperature
            }
        )
        
        return response.text
    
    def get_cost_estimate(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for Gemini"""
        
        input_cost = (input_tokens / 1_000_000) * 0.5
        output_cost = (output_tokens / 1_000_000) * 1.5
        
        return input_cost + output_cost


class LocalModelProvider(BaseLLMProvider):
    """Local model provider (Hugging Face, Llama, etc.)"""
    
    def __init__(self, api_key: str = None, model: str = "meta-llama/Llama-2-7b-chat-hf"):
        super().__init__(api_key or "", model)
        
        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM
            import torch
            
            logger.info(f"Loading local model: {model}")
            
            self.tokenizer = AutoTokenizer.from_pretrained(model)
            self.model_instance = AutoModelForCausalLM.from_pretrained(
                model,
                torch_dtype=torch.float16,
                device_map="auto"
            )
            
            logger.info(f"Local model loaded: {model}")
            
        except ImportError:
            raise ImportError("Please install: pip install transformers torch")
    
    def chat(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.7) -> str:
        """Generate with local model"""
        
        import torch
        
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model_instance.device)
        
        outputs = self.model_instance.generate(
            **inputs,
            max_new_tokens=max_tokens,
            temperature=temperature,
            do_sample=True
        )
        
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        response = response[len(prompt):].strip()
        
        return response
    
    def chat_with_history(
        self,
        messages: List[Dict],
        max_tokens: int = 4000,
        temperature: float = 0.7
    ) -> str:
        """Chat with history"""
        
        prompt = "\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])
        return self.chat(prompt, max_tokens, temperature)
    
    def get_cost_estimate(self, input_tokens: int, output_tokens: int) -> float:
        """Local models are free!"""
        return 0.0


class LLMProvider:
    """
    Factory class for creating LLM providers
    
    Supports:
    - openrouter: OpenRouter (100+ models, one API) ⭐ NEW!
    - claude: Anthropic Claude (Sonnet, Opus)
    - openai: OpenAI GPT (GPT-4, GPT-3.5)
    - gemini: Google Gemini
    - local: Local models (Llama, Mistral, etc.)
    """
    
    PROVIDERS = {
        'openrouter': OpenRouterProvider,  # NEW!
        'claude': ClaudeProvider,
        'openai': OpenAIProvider,
        'gemini': GeminiProvider,
        'local': LocalModelProvider
    }
    
    @staticmethod
    def create(
        provider_type: str = None,
        api_key: str = None,
        model: str = None
    ) -> BaseLLMProvider:
        """
        Create an LLM provider
        
        Args:
            provider_type: 'openrouter', 'claude', 'openai', 'gemini', or 'local'
            api_key: API key (read from env if not provided)
            model: Specific model to use
        
        Returns:
            LLM provider instance
        
        Examples:
            # OpenRouter (NEW!)
            provider = LLMProvider.create('openrouter', model='anthropic/claude-3-sonnet')
            provider = LLMProvider.create('openrouter', model='openai/gpt-4-turbo')
            provider = LLMProvider.create('openrouter', model='meta-llama/llama-3-70b')
            
            # Direct providers
            provider = LLMProvider.create('claude', api_key='sk-ant-...')
            provider = LLMProvider.create('openai', model='gpt-4-turbo')
            
            # Auto-detect from environment
            provider = LLMProvider.create()
        """
        
        # Auto-detect provider from environment if not specified
        if provider_type is None:
            provider_type = LLMProvider._auto_detect_provider()
        
        provider_type = provider_type.lower()
        
        if provider_type not in LLMProvider.PROVIDERS:
            raise ValueError(
                f"Unknown provider: {provider_type}. "
                f"Choose from: {list(LLMProvider.PROVIDERS.keys())}"
            )
        
        # Get API key from environment if not provided
        if api_key is None:
            api_key = LLMProvider._get_api_key(provider_type)
        
        # Get provider class
        provider_class = LLMProvider.PROVIDERS[provider_type]
        
        # Create instance
        if model:
            return provider_class(api_key, model)
        else:
            return provider_class(api_key)
    
    @staticmethod
    def _auto_detect_provider() -> str:
        """Auto-detect available provider from environment"""
        
        # Check for OpenRouter first (NEW!)
        if os.getenv('OPENROUTER_API_KEY'):
            logger.info("Auto-detected provider: OpenRouter")
            return 'openrouter'
        elif os.getenv('ANTHROPIC_API_KEY'):
            logger.info("Auto-detected provider: Claude")
            return 'claude'
        elif os.getenv('OPENAI_API_KEY'):
            logger.info("Auto-detected provider: OpenAI")
            return 'openai'
        elif os.getenv('GOOGLE_API_KEY'):
            logger.info("Auto-detected provider: Gemini")
            return 'gemini'
        else:
            logger.info("No API key found, using local model")
            return 'local'
    
    @staticmethod
    def _get_api_key(provider_type: str) -> Optional[str]:
        """Get API key from environment"""
        
        key_map = {
            'openrouter': 'OPENROUTER_API_KEY',  # NEW!
            'claude': 'ANTHROPIC_API_KEY',
            'openai': 'OPENAI_API_KEY',
            'gemini': 'GOOGLE_API_KEY',
            'local': None
        }
        
        env_var = key_map.get(provider_type)
        
        if env_var:
            api_key = os.getenv(env_var)
            if not api_key:
                raise ValueError(
                    f"API key not found. Please set {env_var} environment variable."
                )
            return api_key
        
        return None


# Popular OpenRouter models for reference
OPENROUTER_MODELS = {
    # Anthropic Claude
    'claude-opus': 'anthropic/claude-3-opus',
    'claude-sonnet': 'anthropic/claude-3-sonnet',
    'claude-haiku': 'anthropic/claude-3-haiku',
    
    # OpenAI GPT
    'gpt-4-turbo': 'openai/gpt-4-turbo',
    'gpt-4': 'openai/gpt-4',
    'gpt-3.5': 'openai/gpt-3.5-turbo',
    
    # Google Gemini
    'gemini-pro': 'google/gemini-pro',
    
    # Meta Llama
    'llama-3-70b': 'meta-llama/llama-3-70b-instruct',
    'llama-3-8b': 'meta-llama/llama-3-8b-instruct',
    
    # Mistral
    'mixtral-8x7b': 'mistralai/mixtral-8x7b-instruct',
    'mixtral-8x22b': 'mistralai/mixtral-8x22b-instruct',
    
    # See all models: https://openrouter.ai/models
}


# Example usage
if __name__ == "__main__":
    
    print("\n" + "="*80)
    print("LLM PROVIDER TEST - WITH OPENROUTER!")
    print("="*80)
    
    test_prompt = "Analyze this earnings call: 'Q4 revenue up 15%, CEO confident about 2024'"
    
    # Test OpenRouter
    if os.getenv('OPENROUTER_API_KEY'):
        print("\n" + "="*80)
        print("Testing OpenRouter")
        print("="*80)
        
        try:
            # Test with Claude via OpenRouter
            provider = LLMProvider.create('openrouter', model='anthropic/claude-3-sonnet')
            print(f"✅ OpenRouter provider created")
            print(f"   Model: {provider.model}")
            
            print("\nSending test prompt...")
            response = provider.chat(test_prompt, max_tokens=500, temperature=0.3)
            
            print("\n📊 Response:")
            print(response[:500])
            
            # Cost estimate
            cost = provider.get_cost_estimate(100, 200)
            print(f"\n💰 Estimated cost: ${cost:.4f}")
            
        except Exception as e:
            print(f"❌ Error testing OpenRouter: {e}")
    
    print("\n" + "="*80)
    print("Test complete!")
    print("="*80)
    
    print("\n💡 OpenRouter Benefits:")
    print("   • Access 100+ models through ONE API")
    print("   • Switch models without code changes")
    print("   • Competitive pricing")
    print("   • See all models: https://openrouter.ai/models")
