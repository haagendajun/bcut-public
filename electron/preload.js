// 화면(웹)에 꼭 필요한 기능만 열어 준다. Node 기능은 화면에 노출하지 않는다.
const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('bcutShell', {
  // 끌어다 놓은 폴더·파일의 실제 경로
  pathForFile: (file) => webUtils.getPathForFile(file),
  // 맥 기본 폴더 선택 창 (취소하면 null)
  chooseFolder: () => ipcRenderer.invoke('choose-folder'),
  // 메뉴의 "폴더 열기…"에서 고른 경로를 받는다
  onOpenFolder: (cb) => ipcRenderer.on('open-folder', (_e, p) => cb(p)),
});
