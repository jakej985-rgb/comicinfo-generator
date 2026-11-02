## 2024-11-02 - Regex Compilation Optimization
**Learning:** Python's `re` module recompiles regex patterns in loops if they are defined inline, which can be a significant bottleneck during high-volume operations like parsing thousands of filenames or matching tags.
**Action:** Pre-compile regex patterns into module-level constants (e.g., `_PATTERN = re.compile(r'...')`) and use `_PATTERN.search()` instead of `re.search()` when the pattern is used repeatedly.
