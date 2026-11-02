## 2024-05-18 - Prevent Zip Bomb Vulnerability
**Vulnerability:** Untrusted zip archives (CBR/CBZ) were being read completely into memory using `zipfile.ZipFile.read()` without validating the total uncompressed size, opening the app up to Zip Bomb (decompression bomb) resource exhaustion attacks.
**Learning:** Python's `zipfile` module will blindly allocate memory up to the uncompressed size of the file being read.
**Prevention:** Check the `file_size` attribute of the `ZipInfo` object using `zipfile.ZipFile.getinfo()` before invoking `.read()`. Do not read files that exceed a reasonable limit (e.g., 100MB).
