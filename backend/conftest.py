"""
Root conftest.py — ensure the backend/ directory (and thus 'app/' and 'scripts/')
are importable from any test run started in backend/.
"""
import sys
import os

# Add the backend root to sys.path so that 'app.*' and 'scripts.*' resolve correctly
sys.path.insert(0, os.path.dirname(__file__))
