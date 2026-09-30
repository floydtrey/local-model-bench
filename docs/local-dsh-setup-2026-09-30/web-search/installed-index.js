import z from "@deepseek-ai/schemastery";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { WebError } from "@deepseek-ai/dsh-web";
//#region src/browser.ts
/**
* agent-browser CLI orchestration for the local-Chrome search provider.
*
* Responsibilities:
*  - Resolve the `agent-browser` executable (configured full path â†’ PATH â†’
*    WSL-interop Windows npm global â†’ actionable error), cached per configured
*    path.
*  - Verify the CLI version is â‰¥ {@link MIN_AGENT_BROWSER_VERSION} once.
*  - Run CLI commands as subprocesses with a hard per-call timeout and kill on
*    expiry. agent-browser can HANG on some failure modes (missing executable,
*    unwritable profile), so the caller's timeout is the backstop and the
*    known failure signatures are mapped to actionable errors.
*
* @module dsh-web-search-chrome/browser
*/
/** The minimum agent-browser release this provider supports (PRD Â§5). */
const MIN_AGENT_BROWSER_VERSION = [
	0,
	34,
	0
];
/** Stable WebError code for provider-side failures (shared vocabulary). */
const WEB_PROVIDER_ERROR = "WEB_PROVIDER_ERROR";
/** Successful resolutions keyed by the configured path ('' = default name). */
const resolvedByPath = /* @__PURE__ */ new Map();
/** Binary paths whose version has already been verified as â‰¥ the minimum. */
const versionOkByBinary = /* @__PURE__ */ new Set();
/**
* Resolve the agent-browser executable, caching only a successful resolution
* per configured path (a missing binary is re-probed per call so a later
* `agent-browser install` is picked up, and a config change re-probes).
*
* Probe order (PRD Â§4.2): configured full path â†’ PATH lookup for the bare
* name â†’ (WSL detected and a Windows npm global exists) interop path. Returns
* `null` when nothing is found so the caller can raise the actionable
* "install agent-browser" error instead of letting agent-browser hang on a
* missing binary.
*
* @param configuredPath - the `agentBrowserPath` config value ('' when unset).
* @returns the executable path, or `null`.
*/
function resolveAgentBrowser(configuredPath) {
	const key = configuredPath ?? "";
	const hit = resolvedByPath.get(key);
	if (hit !== void 0) return hit;
	const found = probeAgentBrowser(configuredPath);
	if (found !== null) resolvedByPath.set(key, found);
	return found;
}
/** Reset the cached resolution (used by tests). */
function _resetResolvedBinary() {
	resolvedByPath.clear();
	versionOkByBinary.clear();
}
function probeAgentBrowser(configuredPath) {
	const bare = configuredPath !== void 0 && configuredPath.length > 0 ? configuredPath : "agent-browser";
	if (bare !== "agent-browser" && (bare.includes("/") || bare.includes("\\") || path.isAbsolute(bare))) return isExecutableFile(bare) ? bare : null;
	const fromPath = findInPath(bare);
	if (fromPath !== null) return fromPath;
	if (bare === "agent-browser" && isWsl()) {
		const interop = findWslWindowsAgentBrowser();
		if (interop !== null) return interop;
	}
	return null;
}
/** Whether `file` exists and is executable. */
function isExecutableFile(file) {
	try {
		fs.accessSync(file, fs.constants.X_OK);
		return fs.statSync(file).isFile();
	} catch {
		return false;
	}
}
/** Look for an executable named `bin` in every PATH entry (Windows honors PATHEXT). */
function findInPath(bin) {
	const entries = (process.env.PATH ?? "").split(path.delimiter).filter(Boolean);
	const exts = process.platform === "win32" ? (process.env.PATHEXT ?? ".COM;.EXE;.BAT;.CMD").split(";").filter(Boolean) : [""];
	for (const dir of entries) for (const ext of exts) {
		const candidate = path.join(dir, `${bin}${ext.toLowerCase()}`);
		if (isExecutableFile(candidate)) return candidate;
	}
	return null;
}
/** WSL detection: the kernel advertises a Microsoft build. */
function isWsl() {
	try {
		return /microsoft/i.test(fs.readFileSync("/proc/version", "utf8"));
	} catch {
		return false;
	}
}
/**
* Windows npm global shims reachable via WSL interop
* (`/mnt/c/Users/<user>/AppData/Roaming/npm/agent-browser`). First match wins.
*/
function findWslWindowsAgentBrowser() {
	const base = "/mnt/c/Users";
	let users;
	try {
		users = fs.readdirSync(base);
	} catch {
		return null;
	}
	for (const user of users) for (const name of [
		"agent-browser",
		"agent-browser.cmd",
		"agent-browser.exe"
	]) {
		const candidate = path.join(base, user, "AppData", "Roaming", "npm", name);
		if (isExecutableFile(candidate)) return candidate;
	}
	return null;
}
/**
* Check the CLI version once per binary (cached per resolved path). The check
* is deliberately lazy (first use), not part of `available()`, because spawning
* a process is not a "cheap" usability check; the actionable upgrade error
* belongs at search time. A later switch to a different binary re-checks that
* binary's version.
* @param binary - the resolved executable path.
* @param timeoutMs - budget for the version probe.
* @throws {@link WebError} when the version is below the minimum.
*/
async function ensureAgentBrowserVersion(binary, timeoutMs) {
	if (versionOkByBinary.has(binary)) return;
	const { stdout, stderr } = await execAgentBrowser(binary, ["--version"], { timeoutMs });
	const match = String(stdout).trim().match(/agent-browser\s+(\d+)\.(\d+)\.(\d+)/);
	if (!match) throw new WebError(`Could not parse agent-browser version from "${String(stdout).trim() || String(stderr).trim()}". Expected agent-browser ${MIN_AGENT_BROWSER_VERSION.join(".")} or newer.`, WEB_PROVIDER_ERROR);
	const found = [
		match[1],
		match[2],
		match[3]
	].map((part) => Number(part));
	if (MIN_AGENT_BROWSER_VERSION.some((v, i) => (found[i] ?? 0) < v)) throw new WebError(`agent-browser ${found.join(".")} is too old; ${MIN_AGENT_BROWSER_VERSION.join(".")} or newer is required. Upgrade with: npm install -g agent-browser@latest`, WEB_PROVIDER_ERROR);
	versionOkByBinary.add(binary);
}
/**
* Run one agent-browser CLI command and capture stdout/stderr.
* @param binary - the executable path.
* @param args - CLI arguments (no shell quoting needed; spawned directly).
* @param options - `{ timeoutMs, signal, stdin }`; `stdin` is written to the
*   child's stdin (used by `eval --stdin`), then the pipe is closed.
* @returns `{ stdout, stderr, code }`.
* @throws {@link WebError} on timeout or non-zero exit.
*/
async function execAgentBrowser(binary, args, options = {}) {
	const { timeoutMs = 2e4, signal, stdin } = options;
	return new Promise((resolve, reject) => {
		let child;
		try {
			const spawnBinary = binary;
const spawnArgs = process.platform === "win32"
    ? args
    : args;

child = spawn(spawnBinary, spawnArgs, {
				stdio: [
					"pipe",
					"pipe",
					"pipe"
				],
				windowsHide: true,
				detached: process.platform !== "win32"
			});
		} catch (error) {
			reject(new WebError(`Failed to start agent-browser: ${String(error)}`, WEB_PROVIDER_ERROR, { cause: error }));
			return;
		}
		let stdout = "";
		let stderr = "";
		let settled = false;
		if (stdin !== void 0) try {
			child.stdin?.end(stdin);
		} catch {}
		else try {
			child.stdin?.end();
		} catch {}
		const killTree = () => {
			try {
				if (child.pid === void 0) return;
				if (process.platform === "win32") spawn("taskkill", [
					"/pid",
					String(child.pid),
					"/T",
					"/F"
				], { stdio: "ignore" });
				else process.kill(-child.pid, "SIGKILL");
			} catch {}
		};
		const onAbort = () => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			killTree();
			reject(new WebError("Search aborted", "WEB_ABORTED", { cause: signal?.reason }));
		};
		const timer = setTimeout(() => {
			if (settled) return;
			settled = true;
			killTree();
			signal?.removeEventListener("abort", onAbort);
			reject(new WebError(`agent-browser command timed out after ${timeoutMs}ms: ${binary} ${args.join(" ")}`, WEB_PROVIDER_ERROR));
		}, timeoutMs);
		if (signal !== void 0) {
			if (signal.aborted) {
				onAbort();
				return;
			}
			signal.addEventListener("abort", onAbort, { once: true });
		}
		child.stdout?.on("data", (chunk) => {
			stdout += chunk;
		});
		child.stderr?.on("data", (chunk) => {
			stderr += chunk;
		});
		child.on("error", (error) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			signal?.removeEventListener("abort", onAbort);
			reject(new WebError(`agent-browser failed to start: ${String(error)}`, WEB_PROVIDER_ERROR, { cause: error }));
		});
		child.on("close", (code) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			signal?.removeEventListener("abort", onAbort);
			if (code !== null && code !== 0) {
				reject(agentBrowserExitError(code, stderr, args));
				return;
			}
			if (code === null) {
				reject(new WebError(`agent-browser command was killed: ${binary} ${args.join(" ")}`, WEB_PROVIDER_ERROR));
				return;
			}
			resolve({
				stdout,
				stderr,
				code
			});
		});
	});
}
/** Map a non-zero CLI exit to a readable WebError, scanning stderr signatures. */
function agentBrowserExitError(code, stderr, args) {
	const err = String(stderr ?? "");
	const joined = args.join(" ");
	if (/SingletonLock|ProcessSingleton|already in use/i.test(err)) return new WebError("Chrome is running. Close all Chrome windows before searching, or point profilePath at a dedicated profile directory.", WEB_PROVIDER_ERROR);
	if (/Chrome exited early|exited before providing DevTools URL|chrome.*error while loading shared libraries/i.test(err)) return new WebError(`Chrome failed to start (exit code ${code}). Install Chrome or run: agent-browser install${err.length > 0 ? ` (${firstLines(err, 2)})` : ""}`, WEB_PROVIDER_ERROR);
	return new WebError(`agent-browser command failed (exit code ${code}): ${joined}${err.length > 0 ? ` â€” ${firstLines(err, 2)}` : ""}`, WEB_PROVIDER_ERROR);
}
/** First `n` non-empty stderr lines, joined. */
function firstLines(stderr, n) {
	return stderr.split("\n").map((l) => l.trim()).filter(Boolean).slice(0, n).join(" | ");
}
/**
* Default disk-cache file path for the provider (PRD Â§10 decision D5):
* POSIX `~/.cache/dsh-web-search-chrome/cache.json`, Windows
* `%LOCALAPPDATA%\dsh-web-search-chrome\cache.json`.
*/
function defaultCachePath() {
	if (process.platform === "win32") {
		const base = process.env.LOCALAPPDATA ?? os.homedir();
		return path.join(base, "dsh-web-search-chrome", "cache.json");
	}
	return path.join(os.homedir(), ".cache", "dsh-web-search-chrome", "cache.json");
}
/**
* Validate and prepare the profile directory: create it (agent-browser creates
* it too, but pre-creating turns an unwritable-parent hang into a fast,
* actionable error).
* @param profilePath - the configured Chrome profile directory.
* @throws {@link WebError} when the directory cannot be created.
*/
function ensureProfileDirectory(profilePath) {
	if (profilePath.length === 0) throw new WebError("profilePath is required. Configure it in the web-search-chrome plugin config (see README).", WEB_PROVIDER_ERROR);
	try {
		fs.mkdirSync(profilePath, { recursive: true });
	} catch (error) {
		throw new WebError(`Chrome profile not found at "${profilePath}" and could not be created: ${String(error.message ?? error)}. Install Chrome or check --profile path.`, WEB_PROVIDER_ERROR, { cause: error });
	}
	try {
		fs.accessSync(profilePath, fs.constants.W_OK | fs.constants.X_OK);
	} catch {
		throw new WebError(`Chrome profile directory "${profilePath}" is not writable. Fix permissions or pick another path for --profile.`, WEB_PROVIDER_ERROR);
	}
}
//#endregion
//#region src/cache.ts
/**
* Caching for the local-Chrome search provider: an in-session map plus a
* JSON-on-disk cache with a TTL (PRD Â§4.5 `cacheTtlMs`, Â§10 decision D5).
*
* Write strategy: last-write-wins, silent on failure (PRD Â§10). Reads are
* tolerant of missing/corrupt files. The disk cache is keyed by query; a hit
* returns the stored sources without touching the browser.
*
* @module dsh-web-search-chrome/cache
*/
/** Cache file format version; bump to invalidate old files. */
const CACHE_VERSION = 1;
/**
* Create the provider's cache.
* @param options - `{ diskPath, ttlMs }`; `ttlMs <= 0` disables the disk cache
*   (the session cache always stays on, per Q4 "åŒ query ç§’å›ž").
* @returns a cache handle.
*/
function createCache(options) {
	const { diskPath, ttlMs } = options;
	/** Session entries: query â†’ { fetchedAt, result }. */
	const session = /* @__PURE__ */ new Map();
	/** Disk entries, lazily loaded: query â†’ { fetchedAt, result }. */
	let disk = void 0;
	function loadDisk() {
		if (disk !== void 0 || ttlMs <= 0 || diskPath.length === 0) return;
		disk = /* @__PURE__ */ new Map();
		try {
			const raw = JSON.parse(fs.readFileSync(diskPath, "utf8"));
			if (raw && raw.version === 1 && raw.entries && typeof raw.entries === "object") {
				for (const [query, entry] of Object.entries(raw.entries)) if (entry && Array.isArray(entry.sources) && typeof entry.fetchedAt === "number") disk.set(query, {
					fetchedAt: entry.fetchedAt,
					result: {
						sources: entry.sources,
						truncated: false
					}
				});
			}
		} catch {}
	}
	/** Look up a query in session cache, then disk cache. */
	function get(query) {
		const now = Date.now();
		const sessionEntry = session.get(query);
		if (sessionEntry !== void 0) return sessionEntry.result;
		if (ttlMs <= 0) return void 0;
		loadDisk();
		const diskEntry = disk?.get(query);
		if (diskEntry !== void 0 && now - diskEntry.fetchedAt <= ttlMs) {
			const result = diskEntry.result;
			session.set(query, {
				fetchedAt: diskEntry.fetchedAt,
				result
			});
			return result;
		}
	}
	/** Store a result in session cache and (TTL enabled) disk cache. */
	function set(query, result) {
		const now = Date.now();
		session.set(query, {
			fetchedAt: now,
			result
		});
		if (ttlMs <= 0 || diskPath.length === 0) return;
		loadDisk();
		disk?.set(query, {
			fetchedAt: now,
			result
		});
		writeDiskSilently();
	}
	/** Rewrite the whole disk file; failures are silent (last-write-wins). */
	function writeDiskSilently() {
		if (disk === void 0) return;
		const entries = {};
		for (const [query, entry] of disk) entries[query] = {
			fetchedAt: entry.fetchedAt,
			sources: entry.result.sources
		};
		try {
			fs.mkdirSync(path.dirname(diskPath), { recursive: true });
			const tmp = `${diskPath}.tmp-${process.pid}`;
			fs.writeFileSync(tmp, JSON.stringify({
				version: 1,
				entries
			}, null, 2), "utf8");
			fs.renameSync(tmp, diskPath);
		} catch {}
	}
	return {
		get,
		set
	};
}
//#endregion
//#region src/serp.ts
/** How long the page-side poll waits for the results container (ms). */
const SERP_WAIT_MS = 1e4;
const EXTRACTION_SCRIPT = `(async () => {
  const deadline = Date.now() + ${SERP_WAIT_MS};
  const host = location.hostname;
  // Engine detection: hostname first; DOM containers as fallback (also covers
  // file:// fixtures and redirect landing pages).
  const isBing = /bing\\./.test(host) || !!document.querySelector('#b_results');
  const isGoogle = /google\\./.test(host) || !!document.querySelector('#search, #rso');
  let blocked = (isGoogle && (location.href.includes('/sorry') || /unusual traffic/i.test(document.body ? document.body.innerText.slice(0, 4000) : '')))
    || (isBing && /(captcha|are you a robot|verify you're human|unusual traffic)/i.test(location.href + ' ' + (document.body ? document.body.innerText.slice(0, 4000) : '')));
  let consent = (isGoogle && (location.href.includes('consent.google') || /(before you continue to google|accept all|i agree.*google)/i.test(document.body ? document.body.innerText.slice(0, 4000) : '')))
    || (isBing && /(manage cookies|privacy settings|personalised search)/i.test(document.body ? document.body.innerText.slice(0, 2000) : '') && !location.href.includes('/search'));
  // Wait until the result list is populated AND stable: engines render
  // progressively (Bing especially), and extracting mid-render yields a
  // partial list. "Stable" = the same result count for 3 consecutive polls.
  let lastCount = -1;
  let stableFor = 0;
  const countResults = () => isBing
    ? document.querySelectorAll('#b_results h2').length
    : document.querySelectorAll('#search a:has(h3), #rso a:has(h3)').length;
  while (Date.now() < deadline) {
    const n = countResults();
    if (n > 0 && n === lastCount) {
      stableFor += 1;
      if (stableFor >= 3) break;
    } else {
      lastCount = n;
      stableFor = 0;
    }
    const text = document.body ? document.body.innerText.slice(0, 4000) : '';
    blocked = blocked || (isGoogle && (location.href.includes('/sorry') || /unusual traffic/i.test(text)))
      || (isBing && /(captcha|are you a robot|verify you're human|unusual traffic)/i.test(location.href + ' ' + text));
    consent = consent || (isGoogle && (location.href.includes('consent.google') || /(before you continue to google|accept all|i agree.*google)/i.test(text)))
      || (isBing && /(manage cookies|privacy settings|personalised search)/i.test(text.slice(0, 2000)) && !location.href.includes('/search'));
    if (blocked || consent) break;
    await new Promise((r) => setTimeout(r, 500));
  }
  const url = location.href;
  const results = [];
  if (isBing) {
    const seen = new Set();
    for (const li of document.querySelectorAll('#b_results > li')) {
      const h2 = li.querySelector('h2');
      const a = h2 ? h2.querySelector('a') : null;
      if (!a) continue;
      const title = (h2.innerText || '').trim();
      if (!title) continue;
      let href = a.href || '';
      try {
        const u = new URL(href);
        if (u.pathname.startsWith('/ck/')) {
          const p = u.searchParams.get('u');
          if (p && /^a1/i.test(p)) {
            const dec = atob(p.slice(2));
            if (/^https?:/i.test(dec)) href = dec;
          }
        }
      } catch {}
      let host2 = '';
      try { host2 = new URL(href).hostname.toLowerCase().replace(/^www\\./, ''); } catch { continue; }
      if (host2 === 'bing.com' || host2.endsWith('.bing.com')) continue;
      if (!/^https?:/i.test(href) || seen.has(href)) continue;
      seen.add(href);
      let snippet = '';
      const cap = li.querySelector('.b_caption p, p');
      if (cap && cap.innerText) snippet = cap.innerText.trim();
      let publishedAt;
      let rest = snippet;
      const dm = rest.match(/^(\\d+)\\s+(minute|hour|day|week|month|year)s?\\s+ago[\\s\\u00b7\\u2022\\u2013\\u2014-]+/);
      const da = rest.match(/^((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\s+\\d{1,2},?\\s+\\d{4})[\\s\\u00b7\\u2022\\u2013\\u2014-]+/);
      if (dm) {
        const units = { minute: 60e3, hour: 36e5, day: 864e5, week: 6048e5, month: 26298e5, year: 315576e5 };
        publishedAt = new Date(Date.now() - Number(dm[1]) * units[dm[2]]).toISOString();
        rest = rest.slice(dm[0].length);
      } else if (da) {
        publishedAt = normalizeDate(da[1]);
        rest = rest.slice(da[0].length);
      }
      results.push({
        url: href,
        title,
        ...(rest && rest.length > 0 ? { snippet: rest } : {}),
        ...(publishedAt ? { publishedAt } : {})
      });
    }
  } else {
    const seen = new Set();
    const anchors = [...document.querySelectorAll(
      '#search a:has(h3), #rso a:has(h3), div#search a[href*="/url?q="], div.g a:has(h3), a:has(h3)'
    )];
    for (const a of anchors) {
      const h3 = a.querySelector('h3');
      if (!h3) continue;
      const title = (h3.innerText || '').trim();
      if (!title) continue;
      let href = a.href || '';
      try {
        const u = new URL(href);
        if (u.pathname === '/url' && u.searchParams.has('q')) href = u.searchParams.get('q');
      } catch {}
      let host2 = '';
      try { host2 = new URL(href).hostname.toLowerCase().replace(/^www\\./, ''); } catch { continue; }
      if (!/^https?:/i.test(href)) continue;
      const g = host2 === 'google.com' || host2.endsWith('.google.com') || /^google\\.(?:com(?:\\.[a-z]{2})?|[a-z]{2,3}(?:\\.[a-z]{2})?)$/.test(host2) || host2 === 'webcache.googleusercontent.com' || host2.endsWith('googleusercontent.com');
      if (g) continue;
      if (seen.has(href)) continue;
      seen.add(href);
      let block = h3.parentElement;
      let snippet = '';
      for (let i = 0; i < 7 && block; i++) {
        const cand = block.querySelector && block.querySelector(
          '.VwiC3b, div[data-sncf], span[style*="-webkit-line-clamp"], div[style*="-webkit-line-clamp"]'
        );
        if (cand && cand.innerText && cand.innerText.trim().length > 10 && cand.innerText.trim() !== title) {
          snippet = cand.innerText.trim();
          break;
        }
        block = block.parentElement;
      }
      if (!snippet) {
        let walker = h3.parentElement;
        for (let i = 0; i < 4 && walker; i++) {
          const candidates = [...walker.querySelectorAll('div, span')]
            .map((e) => (e.innerText || '').trim())
            .filter((t) => t.length > 30 && t !== title && t !== snippet);
          if (candidates.length > 0) { snippet = candidates.sort((x, y) => y.length - x.length)[0]; break; }
          walker = walker.parentElement;
        }
      }
      let publishedAt;
      let rest = snippet;
      const m = rest.match(/^((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\s+\\d{1,2},?\\s+\\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\s+\\d{1,2}|\\d{4}-\\d{2}-\\d{2})[\\s\\u2013\\u2014-]+/);
      if (m) {
        publishedAt = normalizeDate(m[1]);
        rest = rest.slice(m[0].length);
      }
      results.push({
        url: href,
        title,
        ...(rest && rest.length > 0 ? { snippet: rest } : {}),
        ...(publishedAt ? { publishedAt } : {})
      });
    }
  }
  return { url, engine: isBing ? 'bing' : (isGoogle ? 'google' : 'unknown'), blocked, consent, results };
  function normalizeDate(s) {
    const p = s.match(/^([A-Za-z]+)\\s+(\\d{1,2}),?\\s+(\\d{4})$/);
    if (p) {
      const months = { jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12 };
      const mo = months[p[1].toLowerCase().slice(0,3)];
      if (mo) return p[3] + '-' + String(mo).padStart(2,'0') + '-' + String(Number(p[2])).padStart(2,'0');
    }
    const q = s.match(/^(\\d{4})-(\\d{2})-(\\d{2})$/);
    if (q) return s;
    return undefined;
  }
})()`;
/**
* Tolerantly parse `agent-browser eval` stdout into a value. The CLI prints the
* JSON encoding of the expression's value (pretty-printed objects, quoted
* strings, bare numbers); async scripts are awaited. Anything unparseable is
* treated as a plain string so a script error surfaces in the caller's message.
*/
function parseEvalOutput(stdout) {
	const text = String(stdout ?? "").trim();
	if (text.length === 0) return "";
	try {
		return JSON.parse(text);
	} catch {
		return text;
	}
}
/**
* True for Google-internal hosts that must never surface as search results
* (PRD Â§8.6): google.com and its regional domains (google.co.jp, google.com.hk,
* google.de, â€¦), plus webcache/googleusercontent.
*/
function isGoogleInternalUrl(url) {
	let host;
	try {
		host = new URL(url).hostname;
	} catch {
		return false;
	}
	const lower = host.toLowerCase().replace(/^www\./, "");
	return lower === "google.com" || lower.endsWith(".google.com") || /^google\.(?:com(?:\.[a-z]{2})?|[a-z]{2,3}(?:\.[a-z]{2})?)$/.test(lower) || lower === "webcache.googleusercontent.com" || lower.endsWith("googleusercontent.com");
}
/**
* True for Bing-internal hosts (bing.com and all regional subdomains such as
* cn.bing.com). Microsoft's own content sites (msn.com etc.) are real results
* and are NOT filtered.
*/
function isBingInternalUrl(url) {
	let host;
	try {
		host = new URL(url).hostname;
	} catch {
		return false;
	}
	const lower = host.toLowerCase().replace(/^www\./, "");
	return lower === "bing.com" || lower.endsWith(".bing.com");
}
/** Engine-scoped internal-link filter. */
function isEngineInternalUrl(url, engine) {
	return engine === "bing" ? isBingInternalUrl(url) : isGoogleInternalUrl(url);
}
/**
* Normalize a page descriptor into {@link WebSearchSource}s: keep only
* well-formed https URLs, drop engine-internal links, dedupe, and project
* present fields.
* @param descriptor - the object returned by {@link EXTRACTION_SCRIPT}.
* @param engine - the engine (descriptor.engine wins when present).
* @returns the normalized sources.
*/
function mapPageResult(descriptor, engine) {
	if (typeof descriptor !== "object" || descriptor === null || !Array.isArray(descriptor.results)) return [];
	const page = descriptor;
	const effective = engine ?? (page.engine === "bing" || page.engine === "google" ? page.engine : "google");
	const seen = /* @__PURE__ */ new Set();
	const sources = [];
	for (const item of page.results) {
		if (typeof item !== "object" || item === null) continue;
		const url = typeof item.url === "string" ? item.url.trim() : "";
		if (!/^https?:\/\//i.test(url) || seen.has(url)) continue;
		let parsed;
		try {
			parsed = new URL(url);
		} catch {
			continue;
		}
		if (parsed.protocol !== "https:" && parsed.protocol !== "http:") continue;
		if (isEngineInternalUrl(url, effective)) continue;
		seen.add(url);
		sources.push({
			url,
			...typeof item.title === "string" && item.title.length > 0 ? { title: item.title } : {},
			...typeof item.snippet === "string" && item.snippet.length > 0 ? { snippet: item.snippet } : {},
			...typeof item.publishedAt === "string" && item.publishedAt.length > 0 ? { publishedAt: item.publishedAt } : {}
		});
	}
	return sources;
}
/**
* Classify the page state into a stable outcome for the provider.
* @param descriptor - the object returned by {@link EXTRACTION_SCRIPT}.
* @returns `'results' | 'captcha' | 'consent' | 'empty'`.
*/
function classifyPage(descriptor) {
	if (typeof descriptor !== "object" || descriptor === null) return "empty";
	const page = descriptor;
	if (page.blocked === true) return "captcha";
	if (page.consent === true) return "consent";
	if (Array.isArray(page.results) && page.results.length > 0) return "results";
	return "empty";
}
//#endregion
//#region src/provider.ts
/** Stable provider id registered under (PRD Â§2). */
const LOCAL_CHROME_PROVIDER_ID = "local-chrome";
function createSerialQueue() {
	let tail = Promise.resolve();
	return function enqueue(task) {
		const run = tail.then(task, task);
		tail = run.then(() => {}, () => {});
		return run;
	};
}
/** Throw the provider's stable cancellation error when the caller aborted. */
function throwIfAborted(signal) {
	if (signal?.aborted === true) throw new WebError("Search aborted", "WEB_ABORTED", { cause: signal.reason });
}
/**
* The search provider. Options are resolved through a thunk at each operation
* so a future settings section can change config between searches without
* re-registering the provider (mirrors the shipped deepseek provider).
*/
var LocalChromeSearchProvider = class {
	resolveOptions;
	/** Stable id this provider registers under (PRD Â§2). */
	id = LOCAL_CHROME_PROVIDER_ID;
	queue;
	cache;
	cacheDiskPath;
	cacheTtlMs;
	constructor(resolveOptions) {
		this.resolveOptions = resolveOptions;
		this.queue = createSerialQueue();
	}
	/** Cheap, no-network usability check (PRD Â§8.9): the profile is configured
	* and the agent-browser binary resolves across platforms (full path â†’ PATH â†’
	* WSL interop). Detailed actionable errors live at search time. */
	available() {
		const options = this.resolveOptions();
		if (options.profilePath.length === 0) return false;
		return resolveAgentBrowser(options.agentBrowserPath) !== null;
	}
	async search(request, signal) {
		throwIfAborted(signal);
		const options = this.resolveOptions();
		const query = typeof request.query === "string" ? request.query.trim() : "";
		if (query.length === 0) throw new WebError("Search query must be a non-empty string.", WEB_PROVIDER_ERROR);
		this.ensureCache(options);
		const cacheKey = `${options.engine}:${query}`;
		const cached = this.cache?.get(cacheKey);
		if (cached !== void 0) return cached;
		const result = await this.enqueueBrowserSearch(query, request.maxResults, options, signal);
		this.cache?.set(cacheKey, result);
		return result;
	}
	/**
	* Lazily create the cache from the current options, and recreate it when the
	* disk path or TTL changes â€” the options thunk is resolved per operation, so
	* a settings change between searches must take effect without re-registering
	* the provider.
	*/
	ensureCache(options) {
		if (this.cache === void 0 || this.cacheDiskPath !== options.cachePath || this.cacheTtlMs !== options.cacheTtlMs) {
			this.cache = createCache({
				diskPath: options.cachePath,
				ttlMs: options.cacheTtlMs
			});
			this.cacheDiskPath = options.cachePath;
			this.cacheTtlMs = options.cacheTtlMs;
		}
	}
	/**
	* Run one browser search through the serial queue. The whole round trip is
	* bounded by `options.timeoutMs`; agent-browser subprocess calls get their
	* own remaining-time budget and are killed on expiry.
	*/
	enqueueBrowserSearch(query, maxResults, options, signal) {
		return this.queue(async () => {
			throwIfAborted(signal);
			const cacheKey = `${options.engine}:${query}`;
			const cached = this.cache?.get(cacheKey);
			if (cached !== void 0) return cached;
			const deadline = Date.now() + options.timeoutMs;
			return this.runBrowserSearch(query, maxResults, options, signal, deadline);
		});
	}
	async runBrowserSearch(query, maxResults, options, signal, deadline) {
		const binary = resolveAgentBrowser(options.agentBrowserPath);
		if (binary === null) throw new WebError("agent-browser CLI not found. Install with: npm install -g agent-browser (>= 0.34.0)", WEB_PROVIDER_ERROR);
		// Keep every operation on the same dedicated daemon and launch configuration.
		// agent-browser 0.38 reconfigures the browser when profile flags disappear.
		const globalFlags = ["--session", "dsh-web-search", "--profile", options.profilePath];
		if (options.headed) globalFlags.push("--headed");
		let descriptor;
		try {
			await ensureAgentBrowserVersion(binary, remaining(deadline));
			ensureProfileDirectory(options.profilePath);
			throwIfAborted(signal);
			const url = buildSearchUrl(query, typeof maxResults === "number" ? Math.min(maxResults, options.num) : options.num, options.hl, options.engine);
			await execAgentBrowser(binary, [
				...globalFlags,
				"open",
				url
			], {
				timeoutMs: remaining(deadline),
				signal
			});
			throwIfAborted(signal);
			await execAgentBrowser(binary, [
				...globalFlags,
				"wait",
				"--load",
				"domcontentloaded"
			], {
				timeoutMs: remaining(deadline),
				signal
			});
			throwIfAborted(signal);
			descriptor = parseEvalOutput((await runExtractionWithRetry(binary, deadline, signal, globalFlags)).stdout);
		} catch (error) {
			throw asSearchError(error, options.timeoutMs);
		}
		throwIfAborted(signal);
		const engine = options.engine;
		if (typeof descriptor !== "object" || descriptor === null) throw new WebError(`SERP extraction failed: agent-browser returned an unexpected result (${String(descriptor).slice(0, 120)}). This usually means the search engine changed its results page; check src/serp.ts.`, WEB_PROVIDER_ERROR);
		const outcome = classifyPage(descriptor);
		const engineName = engine === "bing" ? "Bing" : "Google";
		if (outcome === "captcha") throw new WebError(`${engineName} returned a captcha/consent page. Open a browser on this network and solve it once, or enable headed mode (headed: true).`, WEB_PROVIDER_ERROR);
		if (outcome === "consent") throw new WebError(`${engineName} returned a consent page. Accept the consent dialog once in a browser on this network, or enable headed mode (headed: true).`, WEB_PROVIDER_ERROR);
		const sources = mapPageResult(descriptor, engine);
		if (sources.length === 0) throw new WebError(`No search results found for query.`, WEB_PROVIDER_ERROR);
		return {
			sources,
			truncated: false
		};
	}
};
/** Remaining milliseconds until the deadline, floored at 0. */
function remaining(deadline) {
	return Math.max(0, deadline - Date.now());
}
/**
* Run the extraction eval, retrying transient CDP context errors. Engines can
* JS-redirect (e.g. /sorry, consent) right after `domcontentloaded`, which
* destroys the page's execution context and makes the CLI report
* `Cannot find default execution context`; the retry lets the navigation
* settle before extracting.
*/
async function runExtractionWithRetry(binary, deadline, signal, globalFlags) {
	const transient = /(Cannot find default execution context|Execution context was destroyed|Cannot find context|target closed|Inspected target navigated or closed|Target closed|navigated or closed)/i;
	let lastError;
	for (let attempt = 0; attempt < 3; attempt += 1) {
		if (attempt > 0) await sleep(600);
		try {
			return await execAgentBrowser(binary, [...globalFlags, "eval", "--stdin"], {
				timeoutMs: remaining(deadline),
				signal,
				stdin: EXTRACTION_SCRIPT
			});
		} catch (error) {
			lastError = error;
			if (!(error instanceof WebError) || !transient.test(error.message)) throw error;
		}
	}
	throw lastError;
}
/** Promise-based sleep. */
function sleep(ms) {
	return new Promise((resolve) => setTimeout(resolve, ms));
}
/** Wrap an agent-browser error so timeouts keep the PRD message shape. */
function asSearchError(error, timeoutMs) {
	if (error instanceof WebError) {
		if (error.code === "WEB_ABORTED") return error;
		if (/command timed out after/i.test(error.message)) return new WebError(`Search timed out after ${timeoutMs}ms.`, WEB_PROVIDER_ERROR, { cause: error });
		return error;
	}
	return new WebError(`Search failed: ${String(error?.message ?? error)}`, WEB_PROVIDER_ERROR, { cause: error });
}
/** Build the engine SERP URL (PRD Â§4.3 step 1, engine-aware). */
function buildSearchUrl(query, num, hl, engine = "bing") {
	const params = new URLSearchParams();
	params.set("q", query);
	if (engine === "bing") {
		params.set("count", String(num));
		if (hl.length > 0) params.set("setlang", hl);
		return `https://www.bing.com/search?${params.toString()}`;
	}
	params.set("num", String(num));
	if (hl.length > 0) params.set("hl", hl);
	return `https://www.google.com/search?${params.toString()}`;
}
//#endregion
//#region src/index.ts
/** Cordis plugin name used by loader diagnostics (row id convention). */
const name = "web-search-chrome";
/** The web seam this provider registers into. */
const inject = ["web"];
/** Provider configuration (PRD Â§4.5, engine default bing per product decision). */
const Config = z.object({
	/**
	* agent-browser executable: a full path (e.g. a Windows-side exe via WSL
	* interop) or a bare name resolved through PATH. Default: `agent-browser`.
	*/
	agentBrowserPath: z.string().default("agent-browser"),
	/**
	* Chrome profile directory for `--profile` (required in 0.1). A dedicated
	* directory is recommended; it is created when missing.
	*/
	profilePath: z.string().required(),
	/** Search engine: `bing` (default) or `google`. */
	engine: z.union([z.const("bing"), z.const("google")]).default("bing"),
	/** Show the Chrome window (`--headed`) instead of headless. */
	headed: z.boolean().default(false),
	/** Engine interface/result language (`hl` for Google, `setlang` for Bing). */
	hl: z.string().default("en"),
	/** Engine result-count parameter â€” upper bound of results requested. */
	num: z.number().min(1).max(100).default(10),
	/** Hard per-search timeout in ms. */
	timeoutMs: z.number().min(1e3).default(2e4),
	/** Disk-cache TTL in ms; 0 disables the disk cache (session cache stays). */
	cacheTtlMs: z.number().min(0).default(864e5),
	/**
	* Serial queue concurrency. 0.1 supports exactly 1 â€” the provider runs a
	* strictly serial promise chain regardless of this value, which exists only
	* as a forward-compatible placeholder for a future concurrent queue.
	*/
	queueConcurrency: z.number().min(1).max(1).default(1),
	/** Disk-cache file path override; defaults to the OS cache directory. */
	cachePath: z.string()
});
/** Default provider options used by {@link resolveOptions} when unset. */
function resolveOptions(ctx, config) {
	return {
		agentBrowserPath: config.agentBrowserPath ?? "agent-browser",
		profilePath: config.profilePath,
		engine: config.engine ?? "bing",
		headed: config.headed ?? false,
		hl: config.hl ?? "en",
		num: config.num ?? 10,
		timeoutMs: config.timeoutMs ?? 2e4,
		cacheTtlMs: config.cacheTtlMs ?? 864e5,
		queueConcurrency: config.queueConcurrency ?? 1,
		cachePath: config.cachePath ?? defaultCachePath()
	};
}
/**
* Register the local-Chrome search provider with `ctx.web`. The options thunk
* snapshots the current config per operation, so a future settings section can
* change values between searches without re-registering the provider.
*/
function apply(ctx, config) {
	const current = () => config;
	ctx.web.registerSearchProvider(new LocalChromeSearchProvider(() => resolveOptions(ctx, current())));
}
//#endregion
export { CACHE_VERSION, Config, EXTRACTION_SCRIPT, LOCAL_CHROME_PROVIDER_ID, LocalChromeSearchProvider, MIN_AGENT_BROWSER_VERSION, SERP_WAIT_MS, _resetResolvedBinary, apply, buildSearchUrl, classifyPage, createCache, defaultCachePath, ensureAgentBrowserVersion, ensureProfileDirectory, execAgentBrowser, inject, isBingInternalUrl, isEngineInternalUrl, isGoogleInternalUrl, mapPageResult, name, parseEvalOutput, resolveAgentBrowser, resolveOptions };






