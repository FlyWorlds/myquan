// Report only the account ID saved by this login process, never credentials.
// This lets independently scanning phones bind to their own UI slot.
const fs = require('node:fs');
const path = require('node:path');
const write = fs.writeFileSync;
fs.writeFileSync = function (file, data, ...options) {
  const result = write.call(this, file, data, ...options);
  try {
    const filename = String(file);
    if (path.basename(path.dirname(filename)) === 'accounts'
        && path.basename(path.dirname(path.dirname(filename))) === 'openclaw-weixin'
        && /^[\w.-]+\.json$/.test(path.basename(filename))) {
      const account = JSON.parse(String(data));
      if (account.token && account.userId) {
        process.stdout.write(`MYQUAN_WECHAT_ACCOUNT:${path.basename(filename, '.json')}\n`);
      }
    }
  } catch { /* Account persistence must never depend on the optional reporter. */ }
  return result;
};
