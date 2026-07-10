param(
    [string]$Url = "http://192.168.1.159:9004/",
    [int]$TimeoutMs = 30000,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")
Set-Location -LiteralPath $root

$runtime = Join-Path $root "_codex_runtime\playwright-ui-check"
$artifactRoot = Join-Path $root "_codex_runtime\artifacts\ui-check"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outDir = Join-Path $artifactRoot $stamp
$browserDir = Join-Path $runtime "browsers"

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

function Get-ToolPath([string[]]$Names) {
    foreach ($name in $Names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd -and $cmd.Source) {
            return $cmd.Source
        }
    }
    return $null
}

$node = Get-ToolPath @("node.exe", "node")
if (-not $node) {
    throw "No encuentro Node.js en PATH."
}

$npm = Get-ToolPath @("npm.cmd", "npm")
if (-not $npm) {
    throw "No encuentro npm en PATH."
}

$env:PLAYWRIGHT_BROWSERS_PATH = $browserDir
$playwrightPackage = Join-Path $runtime "node_modules\playwright\package.json"
if (-not (Test-Path -LiteralPath $playwrightPackage)) {
    if ($SkipInstall) {
        throw "Playwright no esta instalado en _codex_runtime y se pidio SkipInstall."
    }
    Write-Output "INSTALANDO: Playwright aislado en _codex_runtime..."
    Push-Location -LiteralPath $runtime
    try {
        if (-not (Test-Path -LiteralPath (Join-Path $runtime "package.json"))) {
            Set-Content -LiteralPath (Join-Path $runtime "package.json") -Encoding UTF8 -Value '{"private":true,"type":"commonjs"}'
        }
        & $npm install --no-audit --no-fund playwright
        if ($LASTEXITCODE -ne 0) {
            throw "npm install playwright fallo con codigo $LASTEXITCODE."
        }
        $playwrightCli = Join-Path $runtime "node_modules\.bin\playwright.cmd"
        & $playwrightCli install chromium
        if ($LASTEXITCODE -ne 0) {
            throw "playwright install chromium fallo con codigo $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
}

$runner = Join-Path $outDir "ui_check_runner.js"
$runnerSource = @'
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const url = process.env.UI_CHECK_URL || "http://192.168.1.159:9004/";
const outDir = process.env.UI_CHECK_OUT_DIR || process.cwd();
const timeoutMs = Number(process.env.UI_CHECK_TIMEOUT_MS || "30000");
const screenshotPath = path.join(outDir, "delay-audio-ui.png");
const resultPath = path.join(outDir, "resultado.json");

const consoleItems = [];
const pageErrors = [];
const failedRequests = [];
const responseErrors = [];

function clip(text, limit = 500) {
  const value = String(text || "");
  return value.length > limit ? value.slice(0, limit) + "..." : value;
}

function writeResult(result) {
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), "utf8");
}

(async () => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 1366, height: 900 },
      deviceScaleFactor: 1,
    });
    const page = await context.newPage();

    page.on("console", (msg) => {
      if (["error", "warning"].includes(msg.type())) {
        consoleItems.push({ type: msg.type(), text: clip(msg.text()) });
      }
    });
    page.on("pageerror", (err) => {
      pageErrors.push(clip(err && err.stack ? err.stack : err));
    });
    page.on("requestfailed", (request) => {
      failedRequests.push({
        url: clip(request.url(), 300),
        method: request.method(),
        failure: clip(request.failure() ? request.failure().errorText : ""),
      });
    });
    page.on("response", (response) => {
      const status = response.status();
      if (status >= 400) {
        responseErrors.push({ url: clip(response.url(), 300), status });
      }
    });

    const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
    await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
    await page.waitForSelector("body", { timeout: 5000 });

    const before = await page.evaluate(() => {
      const tabs = Array.from(document.querySelectorAll("#tabs [data-tab]")).map((button) => ({
        id: button.dataset.tab || "",
        text: (button.innerText || "").trim(),
        active: button.classList.contains("is-active"),
      }));
      return {
        title: document.title || "",
        bodyText: document.body ? document.body.innerText || "" : "",
        tabs,
        activeTab: (tabs.find((tab) => tab.active) || {}).id || "",
        savedTab: localStorage.getItem("delay-audio-active-tab") || "",
      };
    });

    let persistence = { checked: false, ok: true, message: "sin pestañas comprobables" };
    const targetTab = before.tabs.find((tab) => tab.id === "tv")
      || before.tabs.find((tab) => tab.id && tab.id !== before.activeTab);

    if (targetTab && targetTab.id) {
      await page.evaluate((tabId) => {
        const button = Array.from(document.querySelectorAll("#tabs [data-tab]"))
          .find((item) => item.dataset.tab === tabId);
        if (button) button.click();
      }, targetTab.id);
      await page.waitForTimeout(800);

      const selectedBeforeReload = await page.evaluate(() => {
        const active = document.querySelector("#tabs [data-tab].is-active");
        return {
          activeTab: active ? active.dataset.tab || "" : "",
          savedTab: localStorage.getItem("delay-audio-active-tab") || "",
        };
      });

      await page.reload({ waitUntil: "domcontentloaded", timeout: timeoutMs });
      await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
      await page.waitForTimeout(800);

      const selectedAfterReload = await page.evaluate(() => {
        const active = document.querySelector("#tabs [data-tab].is-active");
        return {
          activeTab: active ? active.dataset.tab || "" : "",
          savedTab: localStorage.getItem("delay-audio-active-tab") || "",
        };
      });

      persistence = {
        checked: true,
        target: targetTab.id,
        ok: selectedBeforeReload.activeTab === targetTab.id
          && selectedBeforeReload.savedTab === targetTab.id
          && selectedAfterReload.activeTab === targetTab.id
          && selectedAfterReload.savedTab === targetTab.id,
        beforeReload: selectedBeforeReload,
        afterReload: selectedAfterReload,
      };
      persistence.message = persistence.ok ? "ok" : "no se conserva la pestaña tras recargar";
    }

    await page.screenshot({ path: screenshotPath, fullPage: true });
    await browser.close();

    const bodyText = before.bodyText || "";
    const consoleErrors = consoleItems.filter((item) => item.type === "error");
    const httpStatus = response ? response.status() : 0;
    const appLoaded = /Delay Audio/i.test((before.title || "") + "\n" + bodyText)
      && before.tabs.length > 0
      && bodyText.trim().length >= 20;

    const result = {
      ok: httpStatus > 0
        && httpStatus < 400
        && appLoaded
        && consoleErrors.length === 0
        && pageErrors.length === 0
        && failedRequests.length === 0
        && responseErrors.length === 0
        && persistence.ok,
      url,
      http_status: httpStatus,
      title: before.title,
      body_chars: bodyText.length,
      tab_count: before.tabs.length,
      tabs: before.tabs,
      persistence,
      console_warnings: consoleItems.filter((item) => item.type === "warning"),
      console_errors: consoleErrors,
      page_errors: pageErrors,
      failed_requests: failedRequests,
      response_errors: responseErrors,
      screenshot: screenshotPath,
      result_json: resultPath,
    };

    writeResult(result);
    console.log(`URL: ${result.url}`);
    console.log(`HTTP: ${result.http_status}`);
    console.log(`TITULO: ${result.title}`);
    console.log(`TABS: ${result.tab_count}`);
    console.log(`PERSISTENCIA: ${result.persistence.checked ? result.persistence.message : "no comprobada"}`);
    console.log(`CONSOLA_ERRORES: ${result.console_errors.length}`);
    console.log(`RED_FALLOS: ${result.failed_requests.length + result.response_errors.length}`);
    console.log(`CAPTURA: ${result.screenshot}`);
    console.log(`RESULTADO_JSON: ${result.result_json}`);
    console.log(result.ok ? "OK" : "FALLO");

    if (!result.ok) {
      process.exitCode = 1;
    }
  } catch (err) {
    if (browser) {
      await browser.close().catch(() => {});
    }
    const result = {
      ok: false,
      url,
      error: clip(err && err.stack ? err.stack : err, 4000),
      screenshot: fs.existsSync(screenshotPath) ? screenshotPath : "",
      result_json: resultPath,
    };
    writeResult(result);
    console.log(`URL: ${url}`);
    console.log(`ERROR: ${clip(result.error, 800)}`);
    console.log(`RESULTADO_JSON: ${resultPath}`);
    process.exitCode = 1;
  }
})();
'@

Set-Content -LiteralPath $runner -Encoding UTF8 -Value $runnerSource

$env:UI_CHECK_URL = $Url
$env:UI_CHECK_OUT_DIR = $outDir
$env:UI_CHECK_TIMEOUT_MS = [string]$TimeoutMs
$env:NODE_PATH = Join-Path $runtime "node_modules"

Write-Output "--- UI CHECK DELAY AUDIO ---"
& $node $runner
$exitCode = $LASTEXITCODE
Write-Output "--- FIN UI CHECK ---"
exit $exitCode
