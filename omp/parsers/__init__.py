"""OMP language parsers."""

from tree_sitter import Language, Parser

from omp.parsers.go import extract_go
from omp.parsers.python import extract_python
from omp.parsers.typescript import extract_typescript, extract_javascript

EXTRACTORS = {
    "python": extract_python,
    "typescript": extract_typescript,
    "tsx": extract_typescript,
    "javascript": extract_javascript,
    "go": extract_go,
}

# Maps file extension (e.g. ".py") to language name (e.g. "python")
EXTENSION_MAP: dict[str, str] = {}
_LANG_REGISTRY: dict[str, tuple[Language, str]] = {}


def _register_languages() -> None:
    """Lazily register all available language grammars."""
    if _LANG_REGISTRY:
        return

    try:
        import tree_sitter_python as tsp

        lang = Language(tsp.language())
        _LANG_REGISTRY[".py"] = (lang, "python")
    except ImportError:
        pass

    try:
        import tree_sitter_typescript as tsts

        ts_lang = Language(tsts.language_typescript())
        tsx_lang = Language(tsts.language_tsx())
        _LANG_REGISTRY[".ts"] = (ts_lang, "typescript")
        _LANG_REGISTRY[".tsx"] = (tsx_lang, "tsx")
    except ImportError:
        pass

    try:
        import tree_sitter_javascript as tsjs

        lang = Language(tsjs.language())
        _LANG_REGISTRY[".js"] = (lang, "javascript")
        _LANG_REGISTRY[".jsx"] = (lang, "javascript")
    except ImportError:
        pass

    try:
        import tree_sitter_go as tsgo

        lang = Language(tsgo.language())
        _LANG_REGISTRY[".go"] = (lang, "go")
    except ImportError:
        pass

    EXTENSION_MAP.clear()
    EXTENSION_MAP.update({ext: name for ext, (_, name) in _LANG_REGISTRY.items()})


def get_parser(language: str) -> Parser:
    """
    Return a tree-sitter Parser configured for the given language.

    Args:
        language: Language name (e.g. "python", "typescript", "javascript", "go", "tsx").

    Returns:
        A configured Parser instance.

    Raises:
        ValueError: If the language is not supported.
    """
    _register_languages()

    lang_obj = None
    for _ext, (lang, name) in _LANG_REGISTRY.items():
        if name == language:
            lang_obj = lang
            break

    if lang_obj is None:
        raise ValueError(
            f"Unsupported language: {language}. Available: {list(EXTRACTORS.keys())}"
        )

    return Parser(lang_obj)


def supported_extensions() -> list[str]:
    """Return the list of supported file extensions (e.g. ['.py', '.ts', '.go'])."""
    _register_languages()
    return sorted(_LANG_REGISTRY.keys())


__all__ = [
    "extract_python",
    "extract_typescript",
    "extract_javascript",
    "extract_go",
    "EXTRACTORS",
    "EXTENSION_MAP",
    "get_parser",
    "supported_extensions",
]
