import sys
try:
    import paddlenlp
    print({'paddlenlp_version': getattr(paddlenlp, '__version__', 'unknown')})
except Exception as exc:
    print({'paddlenlp_import_error': repr(exc)})
