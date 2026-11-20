# Repository workflow

- Group the changes after the published 1.2.3 release into the planned 1.3.0 stable milestone. Keep the versions in `pyproject.toml` and `src/domino_cli.py` consistent.
- The user explicitly requires normal commits during development. Do not create `v1.3.0` or any release tag, create a release, or publish packages unless the user explicitly authorizes that action. A version bump or a passing test run is not release authorization.
- Company LAN validation and acceptance of the latest source on Ubuntu remain pending before the 1.3.0 release. Preserve the published 1.2.3 artifacts and Debian submission materials.
- The root `pypi-token` file is a local credential. Never read, stage, commit, or upload it. Use explicit paths when staging changes.
- Configure shell integration for platform defaults: macOS uses Zsh (`.zshrc`), Ubuntu/Linux uses Bash (`.bashrc`). Do not install Zsh or change the login shell. Preserve existing integration and user settings in other shells; keep both completion scripts available for opt-in use.
- Keep BUILD_CHANNEL as development while 1.3.0 remains unpublished. Preserve the plain --version response; show build fingerprints and the separate kernel version in status. A development build must not be presented as a published release.
