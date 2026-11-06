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

NEW_GET_TS = r'''/** Retrieve the cached context token for a given account+user pair. */
export function getContextToken(accountId: string, userId: string): string | undefined {
  // myquan-patch: disk-fallback-v1
  // CLI / isolated sends never call startAccount.restore — fall back to disk.
  const primaryKey = contextTokenKey(accountId, userId);
  const candidates: string[] = [];
  if (userId) {
    candidates.push(userId);
    if (String(userId).includes("@")) {
      candidates.push(String(userId).split("@")[0]);
    } else {
      candidates.push(`${userId}@im.wechat`);
    }
  }
  const seen = new Set<string>();
  for (const uid of candidates) {
    if (!uid || seen.has(uid)) continue;
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

NEW_FIND_TS = r'''export function findAccountIdsByContextToken(
  accountIds: string[],
  userId: string,
): string[] {
  // myquan-patch: disk-fallback-v1
  return accountIds.filter((id) => Boolean(getContextToken(id, userId)));
}'''

GET_RE = re.compile(
    r"/\*\* Retrieve the cached context token for a given account\+user pair\. \*/\s*"
    r"export function getContextToken\([a-zA-Z0-9_: ,]+\)(?::\s*[a-zA-Z0-9_| ]+)?\s*\{.*?\n\}",
    re.DOTALL,
)
FIND_RE = re.compile(
    r"export function findAccountIdsByContextToken\([a-zA-Z0-9_: ,\n\r\t]+\)(?::\s*[a-zA-Z0-9_| \[\]]+)?\s*\{.*?\n\}",
    re.DOTALL,
)


def _plugin_inbound_files() -> list[Path]:
    results = []
    ext_ts = Path.home() / ".openclaw" / "extensions" / "openclaw-weixin" / "src" / "messaging" / "inbound.ts"
    if ext_ts.is_file():
        results.append(ext_ts)

    root = Path.home() / ".openclaw" / "npm" / "projects"
    if root.is_dir():
        matches = sorted(
            root.glob(
                "tencent-weixin-openclaw-weixin-*/node_modules/"
                "@tencent-weixin/openclaw-weixin/dist/src/messaging/inbound.js"
            )
        )
        if matches:
            results.append(matches[-1])
    return results


def patch_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    is_ts = path.suffix == ".ts"
    if MARKER in text and "restoreContextTokens(accountId)" in text:
        return "already"
    if not GET_RE.search(text):
        raise RuntimeError(f"未找到 getContextToken 函数: {path}")
    if not FIND_RE.search(text):
        raise RuntimeError(f"未找到 findAccountIdsByContextToken 函数: {path}")
    new_get = NEW_GET_TS if is_ts else NEW_GET
    new_find = NEW_FIND_TS if is_ts else NEW_FIND
    text2 = GET_RE.sub(new_get, text, count=1)
    text2 = FIND_RE.sub(new_find, text2, count=1)
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
    files = _plugin_inbound_files()
    if not files:
        print("ERROR: 未找到 openclaw-weixin inbound 文件", file=sys.stderr)
        return 1
    for path in files:
        status = patch_file(path)
        print(f"inbound: {status} -> {path}")
    prune = prune_broken_accounts()
    print(f"accounts.json: {prune}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
