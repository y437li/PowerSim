"""pytest configuration — add src/ to sys.path so 'reference' and 'energy_go' are importable
without requiring 'pip install -e .' in CI/local runs."""
import sys
from pathlib import Path

# Insert src/ at the front so both energy_go and reference packages resolve correctly.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
