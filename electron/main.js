const { app, BrowserWindow, dialog, shell } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const http = require('http')
const { autoUpdater } = require('electron-updater')

const PORT = 8000
const isDev = !app.isPackaged

let backendProcess = null
let mainWindow = null
let splashWindow = null

function getBackendPath() {
  if (isDev) {
    return null // Dev mode: start uvicorn manually
  }
  // Production mode: PyInstaller executable bundled in resources/backend/
  const ext = process.platform === 'win32' ? '.exe' : ''
  return path.join(process.resourcesPath, 'backend', 'backend', `backend${ext}`)
}

function startBackend() {
  if (isDev) {
    console.log('[dev] Please start backend manually: cd .. && uvicorn main:app --port 8000')
    return
  }

  const backendPath = getBackendPath()
  console.log('[backend] Starting:', backendPath)

  backendProcess = spawn(backendPath, [], {
    cwd: path.join(process.resourcesPath, 'backend', 'backend'),
    env: { ...process.env, PORT: String(PORT) },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  backendProcess.stdout.on('data', (d) => console.log('[backend]', d.toString().trim()))
  backendProcess.stderr.on('data', (d) => console.error('[backend]', d.toString().trim()))

  backendProcess.on('exit', (code) => {
    console.warn('[backend] Process exited, code:', code)
  })
}

function waitForBackend(retries = 180, onProgress = null) {
  const total = retries
  return new Promise((resolve, reject) => {
    let backendExited = false

    // Watch for backend process exit to fail fast
    if (backendProcess) {
      backendProcess.on('exit', (code) => {
        backendExited = true
      })
    }

    const attempt = (n) => {
      // If backend process already exited, don't keep retrying
      if (backendExited) {
        reject(new Error('Backend process exited unexpectedly, please check logs'))
        return
      }

      if (onProgress) {
        onProgress(total - n, total)
      }

      http.get(`http://localhost:${PORT}/api/health`, (res) => {
        if (res.statusCode < 500) resolve()
        else if (n > 0) setTimeout(() => attempt(n - 1), 1000)
        else reject(new Error('Backend startup timed out (180s), please check firewall or port usage'))
      }).on('error', () => {
        if (n > 0) setTimeout(() => attempt(n - 1), 1000)
        else reject(new Error('Backend startup timed out (180s), please check firewall or port usage'))
      })
    }
    attempt(retries)
  })
}

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 360,
    height: 200,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: true,
    webPreferences: { contextIsolation: true },
  })

  const html = `
    <html>
    <head><meta charset="utf-8"><style>
      body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:rgba(17,23,35,0.95); color:#f3f7ff; display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; -webkit-app-region:drag; border-radius:16px; }
      h1 { font-size:16px; font-weight:600; margin:0 0 8px; }
      p { font-size:12px; color:#6c7a92; margin:0 0 16px; }
      .bar { width:200px; height:4px; background:rgba(127,178,255,0.15); border-radius:2px; overflow:hidden; }
      .bar-inner { height:100%; background:linear-gradient(90deg,#7fb2ff,#8de3ff); border-radius:2px; transition:width 0.3s; }
    </style></head>
    <body>
      <h1>AIT Auto Register</h1>
      <p id="msg">Starting backend service...</p>
      <div class="bar"><div class="bar-inner" id="progress" style="width:0%"></div></div>
    </body>
    </html>`

  splashWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html))
}

function updateSplashProgress(current, total) {
  if (!splashWindow || splashWindow.isDestroyed()) return
  const pct = Math.min(Math.round((current / total) * 100), 99)
  splashWindow.webContents.executeJavaScript(
    `document.getElementById('progress').style.width='${pct}%';` +
    `document.getElementById('msg').textContent='Starting backend service... (${current}s)';`
  ).catch(() => {})
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.close()
    splashWindow = null
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    title: 'AIT Auto Register',
    show: false,
    webPreferences: {
      contextIsolation: true,
    },
  })

  mainWindow.loadURL(`http://localhost:${PORT}`)
  mainWindow.once('ready-to-show', () => {
    closeSplash()
    mainWindow.show()
  })
  mainWindow.on('closed', () => { mainWindow = null })

  // Open external links in system browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://') || url.startsWith('https://')) {
      shell.openExternal(url)
      return { action: 'deny' }
    }
    return { action: 'allow' }
  })
}

app.whenReady().then(async () => {
  createSplash()
  startBackend()

  try {
    await waitForBackend(180, updateSplashProgress)
  } catch (err) {
    closeSplash()
    dialog.showErrorBox('Startup Failed', err.message)
    app.quit()
    return
  }

  createWindow()

  // ── Auto-update (Windows only, macOS unsigned not supported) ──
  if (process.platform === 'win32' && !isDev) {
    autoUpdater.autoDownload = false
    autoUpdater.autoInstallOnAppQuit = true

    autoUpdater.on('update-available', (info) => {
      dialog.showMessageBox(mainWindow, {
        type: 'info',
        title: 'Update Available',
        message: `New version v${info.version} available, download now?`,
        buttons: ['Download Update', 'Later'],
        defaultId: 0,
      }).then(({ response }) => {
        if (response === 0) {
          autoUpdater.downloadUpdate()
        }
      })
    })

    autoUpdater.on('update-downloaded', () => {
      dialog.showMessageBox(mainWindow, {
        type: 'info',
        title: 'Update Ready',
        message: 'New version downloaded. Restart the app to install.',
        buttons: ['Restart Now', 'Later'],
        defaultId: 0,
      }).then(({ response }) => {
        if (response === 0) {
          autoUpdater.quitAndInstall()
        }
      })
    })

    autoUpdater.on('error', (err) => {
      console.error('[updater] Update check failed:', err.message)
    })

    // Check for updates 10 seconds after startup
    setTimeout(() => autoUpdater.checkForUpdates(), 10000)
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('will-quit', () => {
  if (backendProcess) {
    // On Windows, child_process.kill() doesn't kill the process tree.
    // Use taskkill to ensure all child processes are terminated.
    if (process.platform === 'win32') {
      try {
        require('child_process').execSync(`taskkill /pid ${backendProcess.pid} /T /F`, { stdio: 'ignore' })
      } catch (_) {
        backendProcess.kill()
      }
    } else {
      backendProcess.kill()
    }
    backendProcess = null
  }
})
