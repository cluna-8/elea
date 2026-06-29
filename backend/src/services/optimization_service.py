import logging
import re
from typing import Tuple

logger = logging.getLogger("basa-secure-gateway.optimization")

try:
    # Attempt to import headroom if installed
    import headroom
    HAS_HEADROOM = True
except ImportError:
    HAS_HEADROOM = False
    logger.warning("Headroom library not found. Using native fallback context compressor.")

class OptimizationService:
    @staticmethod
    def compress_context(text: str, enabled: bool = True) -> Tuple[str, int]:
        """
        Compresses the context of the prompt using Headroom (or native fallback).
        Returns:
        1. The compressed text
        2. The number of tokens saved (estimate)
        """
        if not enabled or not text:
            return text, 0

        original_len = len(text)

        if HAS_HEADROOM:
            try:
                # Use headroom's text compressor
                # For this MVP, we use headroom's default text compression interface
                compressed_text = headroom.compress(text)
                saved_tokens = max(0, (original_len - len(compressed_text)) // 4) # Estimate 4 chars per token
                return compressed_text, saved_tokens
            except Exception as e:
                logger.error(f"Error compressing with Headroom: {e}")
                # Fallback to native compression on error
                pass

        # --- Native Fallback Context Compressor ---
        # 1. Strip redundant spaces and multiple newlines
        compressed = re.sub(r'[ \t]+', ' ', text)
        compressed = re.sub(r'\n+', '\n', compressed)
        
        # 2. Strip code comments if prompt contains code blocks
        # Strip Python comments (# ...) and JS/C++ comments (// ...)
        compressed = re.sub(r'#.*$', '', compressed, flags=re.MULTILINE)
        compressed = re.sub(r'//.*$', '', compressed, flags=re.MULTILINE)
        
        # 3. Strip markdown link targets or excessive spacing
        compressed = compressed.strip()
        
        # Calculate saved tokens (rough estimate: 1 token = 4 characters)
        saved_chars = original_len - len(compressed)
        saved_tokens = max(0, saved_chars // 4)
        
        logger.info(f"Context compressed: {original_len} chars -> {len(compressed)} chars (saved ~{saved_tokens} tokens)")
        return compressed, saved_tokens
