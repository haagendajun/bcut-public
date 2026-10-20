// bcut Electron 셸 (Phase 3b S4): 로컬 Python 서버(`bcut serve`)를 띄우고 그 주소를 창으로 보여 준다.
// Nook(Day5)과 같은 구조. 사진이 컴퓨터 밖으로 나가지 않도록 창에서 나가는 요청은 모두 막는다.
const { app, BrowserWindow, Menu, dialog, ipcMain, session } = require('electron');
const { spawn } = require('child_process');
const crypto = require('crypto');
const path = require('path');
const fs = require('fs');
const net = require('net');
const http = require('http');

const NAME = 'bcut';
app.setName(NAME);

let server = null, win = null, base = '', token = '', quitting = false, serverLog = '';

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
}

// 설정: 빌드가 config.json에 파이썬 위치를 적어 둔다 (개발 중에는 환경 변수 BCUT_PYTHON).
function loadConfig() {
  let cfg = {};
  try { cfg = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8')); } catch (_) {}
  return { python: process.env.BCUT_PYTHON || cfg.python };
}

// 같은 포트를 쓰면 "살리기" 기억(브라우저 저장소는 주소+포트별)이 앱을 껐다 켜도 남는다. 사용 중이면 빈 포트로 대체.
const PREFERRED_PORT = 47640;
function freePort(preferred = 0) {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.once('error', () => (preferred ? resolve(freePort(0)) : reject(new Error('빈 포트를 찾지 못했습니다.'))));
    s.listen(preferred, '127.0.0.1', () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}

function waitReady(url, timeoutMs = 30000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      if (!server || server.exitCode !== null) return reject(new Error('서버가 시작 중 종료되었습니다.'));
      const req = http.get(url + '/api/health', { headers: { 'X-Token': token } }, (res) => {
        res.resume();
        res.statusCode === 200 ? resolve() : retry();
      });
      req.on('error', retry);
    };
    const retry = () => (Date.now() - started > timeoutMs ? reject(new Error('서버 시작 시간이 초과되었습니다.')) : setTimeout(tick, 200));
    tick();
  });
}

async function startServer() {
  const cfg = loadConfig();
  if (!cfg.python || !fs.existsSync(cfg.python)) {
    throw new Error(`Python 환경을 찾지 못했습니다:\n${cfg.python}\n\nelectron/build.sh 를 다시 실행해 주세요.`);
  }
  const port = await freePort(PREFERRED_PORT);
  token = crypto.randomBytes(16).toString('hex');
  const dataDir = path.join(app.getPath('userData'), 'data');
  const code = `import sys; from bcut.cli import main; sys.exit(main(['serve','--port','${port}','--data-dir',${JSON.stringify(dataDir)}]))`;
  const env = { ...process.env, BCUT_TOKEN: token, PYTHONUNBUFFERED: '1' };
  server = spawn(cfg.python, ['-B', '-c', code], { env, cwd: app.getPath('userData') });
  const keep = (b) => { serverLog = (serverLog + b.toString()).slice(-4000); };
  server.stdout.on('data', keep);
  server.stderr.on('data', keep);
  server.on('exit', (c) => {
    if (quitting) return;
    dialog.showErrorBox('서버가 종료되었습니다', `종료 코드 ${c}\n\n${serverLog.trim() || '(로그 없음)'}`);
    app.quit();
  });
  base = `http://127.0.0.1:${port}`;
  await waitReady(base);
}

// 사진이 밖으로 나가지 않게: 창이 만드는 요청 중 이 서버(127.0.0.1:<포트>)와 개발자 도구 외에는 모두 취소한다.
function lockDownNetwork() {
  const ses = session.defaultSession;
  ses.webRequest.onBeforeRequest((details, cb) => {
    const u = details.url;
    const ok = u.startsWith(base + '/') || u === base || u.startsWith('devtools:') || u.startsWith('data:') || u.startsWith('blob:');
    cb({ cancel: !ok });
  });
  ses.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
  app.on('web-contents-created', (_e, contents) => {
    contents.setWindowOpenHandler(() => ({ action: 'deny' }));
    contents.on('will-attach-webview', (e) => e.preventDefault());
    contents.on('will-navigate', (e, url) => { if (new URL(url).origin !== base) e.preventDefault(); });
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1180, height: 860, minWidth: 760, minHeight: 560, title: NAME, backgroundColor: '#fafaf8',
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, preload: path.join(__dirname, 'preload.js') },
  });
  win.on('closed', () => { win = null; });
  win.loadURL(`${base}/?t=${token}`);
}

async function pickFolder() {
  const r = await dialog.showOpenDialog(win, { properties: ['openDirectory'], title: '사진 폴더를 고르세요' });
  return r.canceled ? null : r.filePaths[0];
}
ipcMain.handle('choose-folder', pickFolder);

function buildMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: app.name, submenu: [{ role: 'about' }, { type: 'separator' }, { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' }, { type: 'separator' }, { role: 'quit' }] },
    { label: '파일', submenu: [{
      label: '폴더 열기…', accelerator: 'CmdOrCtrl+O',
      click: async () => { const p = await pickFolder(); if (p && win) win.webContents.send('open-folder', p); },
    }] },
    { label: '편집', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
    { label: '보기', submenu: [{ role: 'reload' }, { role: 'toggleDevTools' }, { type: 'separator' }, { role: 'togglefullscreen' }] },
    { label: '윈도우', submenu: [{ role: 'minimize' }, { role: 'zoom' }, { role: 'close' }] },
  ]));
}

function stopServer() {
  quitting = true;
  if (server && server.exitCode === null) {
    server.kill('SIGINT');
    setTimeout(() => { if (server && server.exitCode === null) server.kill('SIGKILL'); }, 1500);
  }
}

app.whenReady().then(async () => {
  try {
    await startServer();
    lockDownNetwork();
    buildMenu();
    createWindow();
  } catch (e) {
    dialog.showErrorBox(`${NAME}을(를) 시작할 수 없어요`, `${e.message}\n\n${serverLog.trim()}`);
    quitting = true;
    stopServer();
    app.quit();
  }
});
app.on('window-all-closed', () => app.quit());
app.on('will-quit', stopServer);
app.on('activate', () => { if (!win && base) createWindow(); });
