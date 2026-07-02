import os
import sys

# Flat modules live in src/ (that's how pywrangler bundles them). Make them
# importable for CPython unit tests.
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
