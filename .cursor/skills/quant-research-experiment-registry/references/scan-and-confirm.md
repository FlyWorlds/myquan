# Scan And Confirm

Scanning is read-only and has two layers: metadata first, candidate content second. Default exclusions include VCS directories, virtual environments, caches, credential files, and private keys.

Candidates are grouped into code, config, data, results, commands, definitions, and unknown files. A host agent must confirm the formal configuration and any assets included in the core fingerprint before writing a registration.
