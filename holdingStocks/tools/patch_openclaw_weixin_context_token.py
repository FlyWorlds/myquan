#!/usr/bin/env python3
"""给 @tencent-weixin/openclaw-weixin 打本地补丁：getContextToken 磁盘回落。

根因（OpenClaw #63172）：
  `openclaw message send` / 部分出站路径会新建进程加载插件，
  不会走 gateway startAccount → restoreContextTokens，
  导致磁盘已有 context_token 但内存为空 → prepare failed。

本补丁让 getContextToken 在内存未命中时自动 restore + 兼容 @im.wechat 别名。
可重复执行（幂等）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MARKER = "myquan-patch: disk-fallback-v1"

NEW_GET = r'''/** Retrieve the cached context token for a given account+user pair. */
export function getContextToken(accountId, userId) {
    // myquan-patch: disk-fallback-v1
    // CLI / isolated sends never call startAccount.restore — fall back to disk.
    const primaryKey = contextTokenKey(accountId, userId);
    const candidates = [];
    if (userId) {
        candidates.push(userId);
        if (String(userId).includes("@")) {
            candidates.push(String(userId).split("@")[0]);
        }
        else {
            candidates.push(`${userId}@im.wechat`);
        }
    }
    const seen = new Set();
    for (const uid of candidates) {
        if (!uid || seen.has(uid))
            continue;
        seen.add(uid);
        const k = contextTokenKey(accountId, uid);
        let val = contextTokenStore.get(k);
        if (val === undefined) {
            restoreContextTokens(accountId);
            val = contextTokenStore.get(k);
        }
        if (val !== undefined) {
            if (k !== primaryKey) {
                contextTokenStore.set(primaryKey, val);
            }
            logger.debug(`getContextToken: key=${primaryKey} found=true storeSize=${contextTokenStore.size}`);
            return val;
        }
    }
    logger.debug(`getContextToken: key=${primaryKey} found=false storeSize=${contextTokenStore.size}`);
    return undefined;
}'''

NEW_FIND = r'''export function findAccountIdsByContextToken(accountIds, userId) {
    // myquan-patch: disk-fallback-v1
    return accountIds.filter((id) => Boolean(getContextToken(id, userId)));
}'''

GET_RE = re.compile(
    r"/\*\* Retrieve the cached context token for a given account\+user pair\. \*/\s*"
    r"export function getContextToken\(accountId, userId\) \{.*?\n\}",
    re.DOTALL,
)
FIND_RE = re.compile(
    r"export function findAccountIdsByContextToken\(accountIds, userId\) \{.*?\n\}",
    re.DOTALL,
)


def _plugin_inbound_js() -> Path | None:
    root = Path.home() / ".openclaw" / "npm" / "projects"
    if not root.is_dir():
        return None
    matches = sorted(
        root.glob(
            "tencent-weixin-openclaw-weixin-*/node_modules/"
            "@tencent-weixin/openclaw-weixin/dist/src/messaging/inbound.js"
        )
    )
    return matches[-1] if matches else None


def patch_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if MARKER in text and "restoreContextTokens(accountId)" in text:
        # already patched; still refresh bodies for idempotent upgrades
        pass
    if not GET_RE.search(text):
        raise RuntimeError(f"未找到 getContextToken 函数: {path}")
    if not FIND_RE.search(text):
        raise RuntimeError(f"未找到 findAccountIdsByContextToken 函数: {path}")
    text2 = GET_RE.sub(NEW_GET, text, count=1)
    text2 = FIND_RE.sub(NEW_FIND, text2, count=1)
    if text2 == text and MARKER in text:
        return "already"
    if MARKER not in text2:
        raise RuntimeError("补丁未写入标记，中止")
    bak = path.with_suffix(path.suffix + ".bak-myquan")
    if not bak.exists():
        bak.write_text(text, encoding="utf-8")
    path.write_text(text2, encoding="utf-8")
    return "patched"


def prune_broken_accounts() -> str:
    """accounts.json 里去掉无 credentials 的僵尸账号，避免多账号歧义。"""
    idx = Path.home() / ".openclaw" / "openclaw-weixin" / "accounts.json"
    if not idx.is_file():
        return "no-index"
    raw = json.loads(idx.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return "skip-shape"
    kept: list[str] = []
    dropped: list[str] = []
    for item in raw:
        aid = str(item).strip()
        if not aid:
            continue
        cred = (
            Path.home()
            / ".openclaw"
            / "openclaw-weixin"
            / "accounts"
            / f"{aid}.json"
        )
        ok = False
        if cred.is_file():
            try:
                data = json.loads(cred.read_text(encoding="utf-8"))
                tok = ""
                if isinstance(data, dict):
                    tok = str(data.get("token") or "").strip()
                ok = bool(tok)
            except (OSError, json.JSONDecodeError):
                ok = False
        if ok:
            kept.append(aid)
        else:
            dropped.append(aid)
    if not dropped:
        return "clean"
    if not kept:
        return "abort-no-valid"
    bak = idx.with_suffix(".json.bak-myquan")
    if not bak.exists():
        bak.write_text(idx.read_text(encoding="utf-8"), encoding="utf-8")
    idx.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"pruned:{','.join(dropped)}"


def main() -> int:
    path = _plugin_inbound_js()
    if path is None:
        print("ERROR: 未找到 openclaw-weixin inbound.js", file=sys.stderr)
        return 1
    status = patch_file(path)
    prune = prune_broken_accounts()
    print(f"inbound.js: {status} -> {path}")
    print(f"accounts.json: {prune}")
    print("请执行: openclaw gateway restart")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
