"""Language detection now lives in core/language.py (shared with the Flask app).
This module re-exports it so `import language; language.detect(...)` keeps working."""

from core.language import (BILINGUAL_SHARE, FUNCTION_WORDS, LANGUAGES, SAMPLE, TITLE_WORDS,  # noqa: F401
                           WORD, detect)
