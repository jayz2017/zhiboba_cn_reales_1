from pathlib import Path
p = Path('tmp_siameseuie_run_result.json')
print({'exists': p.exists(), 'size': p.stat().st_size if p.exists() else 0})
