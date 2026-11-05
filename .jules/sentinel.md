## 2024-05-18 - Prevent Zip Bomb Vulnerability
**Vulnerability:** Untrusted zip archives (CBR/CBZ) were being read completely into memory using `zipfile.ZipFile.read()` without validating the total uncompressed size, opening the app up to Zip Bomb (decompression bomb) resource exhaustion attacks.
**Learning:** Python's `zipfile` module will blindly allocate memory up to the uncompressed size of the file being read.
**Prevention:** Check the `file_size` attribute of the `ZipInfo` object using `zipfile.ZipFile.getinfo()` before invoking `.read()`. Do not read files that exceed a reasonable limit (e.g., 100MB).

## 2026-11-05 - Missing Content-Security-Policy Header
**Vulnerability:** Web UI endpoints served HTML and API responses with X-Frame-Options and X-Content-Type-Options but lacked a Content-Security-Policy (CSP) header, increasing the blast radius of any client-side DOM injection or malicious external asset inclusion.
**Learning:** Modern web frontends displaying scraped third-party metadata and cover images require defense-in-depth boundaries restricting script execution, font/style origins, and network connections.
**Prevention:** Explicitly set `Content-Security-Policy` on all HTTP responses via the server handler base headers, restricting sources to `'self'`, trusted external CDNs, and allowed thumbnail protocols (`data:`, `https:`, `http:`).
