# Installed browser-search snapshot

The web profile installs `dsh-web-search-chrome` 0.1.1. The configured provider is `local-chrome`, with engine `bing`, `agentBrowserPath` pointing to the user's npm `agent-browser.cmd`, and an isolated profile under `.dsh-web-search-chrome/profile`. The installed `agent-browser` package is 0.38.1; Node is v24.21.0. The Chrome profile/cookies were not accessed or copied.

`installed-index.js` is the actual installed package entry point, with account paths redacted. `windows-local-changes.patch` compares it with the existing `index.js.pre-windows-spawn-fix` backup, not a newly downloaded upstream source. It includes encoding/comment differences as well as code changes. The MIT license is retained.

The patch changes the Windows spawning section, but the captured code still calls `spawn` on the resolved executable with argument arrays, while the configured path ends in `.cmd`. Presence of a patch is **not** a successful Windows search test. No browser or search was launched during collection, and this packet makes no claim that the present code is working. The Lab control reference also records a historical observational child failure and explicitly says its classification fix did not repair search connectivity.

For reproducibility, capture provider/engine, actual resolved executable, browser availability, and the returned search/tool result. Search results are changing external data and affect repeatability. Do not include a private browser profile or authentication cookies in a benchmark repository. This snapshot does not install, activate or repair the plugin.
