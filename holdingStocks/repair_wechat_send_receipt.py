"""Idempotent local OpenClaw repair: reject WeChat business failures on HTTP 200."""
from pathlib import Path
import os

OLD = '''  await apiFetch({
    baseUrl: params.baseUrl,
    endpoint: "ilink/bot/sendmessage",
    body: JSON.stringify({ ...params.body, base_info: buildBaseInfo() }),
    token: params.token,
    timeoutMs: params.timeoutMs ?? DEFAULT_API_TIMEOUT_MS,
    label: "sendMessage",
  });'''
NEW = OLD.replace('  await apiFetch({', '  const rawText = await apiFetch({') + '''
  // myquan-patch: validate-send-receipt-v1
  const receipt = JSON.parse(rawText);
  if (!receipt || typeof receipt !== "object" || Array.isArray(receipt)) {
    throw new Error("sendMessage invalid business receipt");
  }
  for (const field of ["ret", "errcode"]) {
    if (field in receipt && receipt[field] !== 0) {
      throw new Error(`sendMessage rejected ${field}=${receipt[field]}`);
    }
  }'''


def repair(path):
    original = path.read_text()
    if 'myquan-patch: validate-send-receipt-v1' in original:
        # JSON/protobuf responses may omit zero-valued success fields ({}).
        strict = 'Array.isArray(receipt)\n      || !("ret" in receipt || "errcode" in receipt)'
        if strict in original:
            path.write_text(original.replace(strict, 'Array.isArray(receipt)'))
            return True
        return False
    if original.count(OLD) != 1:
        raise RuntimeError('OpenClaw send API changed; refusing an unverified patch')
    backup = path.with_suffix('.ts.before-myquan-receipt')
    if not backup.exists():
        backup.write_text(original)
    path.write_text(original.replace(OLD, NEW))
    return True


if __name__ == '__main__':
    root = Path(os.environ.get('OPENCLAW_STATE_DIR') or Path.home()/'.openclaw')
    print('receipt check installed' if repair(root/'extensions/openclaw-weixin/src/api/api.ts') else 'receipt check already present')
