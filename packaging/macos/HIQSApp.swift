import AppKit
import Foundation
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    private var window: NSWindow?
    private var webView: WKWebView?
    private var backend: Process?
    private var outputPipe: Pipe?
    private var outputBuffer = Data()
    private var backendURL: URL?
    private var backendLog: FileHandle?
    private var terminationSignal: DispatchSourceSignal?

    func applicationDidFinishLaunching(_ notification: Notification) {
        installTerminationHandler()
        createWindow()
        startBackend()
        NSApp.activate(ignoringOtherApps: true)
    }

    private func installTerminationHandler() {
        signal(SIGTERM, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        source.setEventHandler { NSApp.terminate(nil) }
        source.resume()
        terminationSignal = source
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        outputPipe?.fileHandleForReading.readabilityHandler = nil
        try? backendLog?.close()
        if let process = backend, process.isRunning {
            process.terminate()
        }
    }

    private func createWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = self
        view.uiDelegate = self

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1440, height: 900),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "HIQS"
        window.minSize = NSSize(width: 980, height: 680)
        window.center()
        window.contentView = view
        window.makeKeyAndOrderFront(nil)
        view.loadHTMLString(
            """
            <html><body style="margin:0;background:#0b1510;color:#dce7df;font-family:-apple-system;display:grid;place-items:center;height:100vh"><div style="text-align:center"><h1>HIQS</h1><p>正在启动本地课程信息库…</p></div></body></html>
            """,
            baseURL: nil
        )
        self.window = window
        self.webView = view
    }

    private func startBackend() {
        guard let resources = Bundle.main.resourceURL else {
            showStartupError("应用资源目录不存在。")
            return
        }
        guard let launch = backendLaunch(resources: resources) else { return }
        let browserRoot = resources.appendingPathComponent("playwright-browsers")

        let process = Process()
        let pipe = Pipe()
        process.executableURL = launch.executable
        process.arguments = launch.arguments + ["ui", "--port", "0", "--no-open"]
        process.currentDirectoryURL = launch.workingDirectory
        process.standardOutput = pipe
        process.standardError = pipe
        var environment = ProcessInfo.processInfo.environment
        if FileManager.default.fileExists(atPath: browserRoot.path) {
            environment["PLAYWRIGHT_BROWSERS_PATH"] = browserRoot.path
        }
        process.environment = environment
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            DispatchQueue.main.async { self?.consumeBackendOutput(data) }
        }
        process.terminationHandler = { [weak self] process in
            guard process.terminationStatus != 0 else { return }
            DispatchQueue.main.async {
                if self?.backendURL == nil {
                    self?.showStartupError("HIQS 后端启动失败，退出码为 \(process.terminationStatus)。")
                }
            }
        }
        do {
            backendLog = openLog()
            try process.run()
            backend = process
            outputPipe = pipe
        } catch {
            showStartupError("HIQS 后端无法启动：\(error.localizedDescription)")
        }
    }

    private func consumeBackendOutput(_ data: Data) {
        try? backendLog?.write(contentsOf: data)
        outputBuffer.append(data)
        guard let text = String(data: outputBuffer, encoding: .utf8) else { return }
        for line in text.split(separator: "\n") {
            guard let range = line.range(of: "http://127.0.0.1:[0-9]+/", options: .regularExpression),
                  let url = URL(string: String(line[range])) else { continue }
            backendURL = url
            outputPipe?.fileHandleForReading.readabilityHandler = nil
            webView?.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
            return
        }
    }

    private func backendLaunch(
        resources: URL
    ) -> (executable: URL, workingDirectory: URL?, arguments: [String])? {
        let bundled = resources.appendingPathComponent("backend/hiqs-backend")
        if FileManager.default.isExecutableFile(atPath: bundled.path) {
            return (bundled, nil, [])
        }

        guard let rootPath = Bundle.main.object(forInfoDictionaryKey: "HIQSProjectRoot") as? String,
              !rootPath.isEmpty else {
            showStartupError("应用没有绑定 HIQS 项目。请在源码目录重新运行构建脚本。")
            return nil
        }
        let root = URL(fileURLWithPath: rootPath, isDirectory: true)
        let executable = root.appendingPathComponent(".venv/bin/python")
        let project = root.appendingPathComponent("pyproject.toml")
        guard FileManager.default.fileExists(atPath: project.path),
              FileManager.default.isExecutableFile(atPath: executable.path) else {
            showStartupError("找不到项目环境。请保留源码目录和 .venv，或重新构建 HIQS.app。")
            return nil
        }
        return (executable, root, ["-m", "hsas"])
    }

    private func openLog() -> FileHandle? {
        let logs = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Logs/HSAS", isDirectory: true)
        try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        let path = logs.appendingPathComponent("desktop.log")
        if !FileManager.default.fileExists(atPath: path.path) {
            FileManager.default.createFile(atPath: path.path, contents: nil)
        }
        guard let handle = try? FileHandle(forWritingTo: path) else { return nil }
        _ = try? handle.seekToEnd()
        return handle
    }

    private func showStartupError(_ message: String) {
        webView?.loadHTMLString(
            """
            <html><body style="margin:0;background:#0b1510;color:#dce7df;font-family:-apple-system;display:grid;place-items:center;height:100vh"><div style="max-width:540px;text-align:center"><h1>HIQS 无法启动</h1><p>\(message)</p></div></body></html>
            """,
            baseURL: nil
        )
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        if url.scheme == "about" ||
            (url.host == backendURL?.host && url.port == backendURL?.port) {
            if navigationAction.shouldPerformDownload {
                decisionHandler(.download)
                return
            }
            if navigationAction.targetFrame == nil {
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
            return
        }
        if url.scheme == "http" || url.scheme == "https" {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptAlertPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping () -> Void
    ) {
        let alert = NSAlert()
        alert.messageText = "HIQS"
        alert.informativeText = message
        alert.addButton(withTitle: "好")
        present(alert) { _ in completionHandler() }
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptConfirmPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping (Bool) -> Void
    ) {
        let alert = NSAlert()
        alert.messageText = "请确认"
        alert.informativeText = message
        alert.addButton(withTitle: "继续")
        alert.addButton(withTitle: "取消")
        present(alert) { response in
            completionHandler(response == .alertFirstButtonReturn)
        }
    }

    private func present(_ alert: NSAlert, completionHandler: @escaping (NSApplication.ModalResponse) -> Void) {
        if let window {
            alert.beginSheetModal(for: window, completionHandler: completionHandler)
        } else {
            completionHandler(alert.runModal())
        }
    }

    func webView(
        _ webView: WKWebView,
        navigationAction: WKNavigationAction,
        didBecome download: WKDownload
    ) {
        download.delegate = self
    }

    func webView(
        _ webView: WKWebView,
        navigationResponse: WKNavigationResponse,
        didBecome download: WKDownload
    ) {
        download.delegate = self
    }

    func download(
        _ download: WKDownload,
        decideDestinationUsing response: URLResponse,
        suggestedFilename: String,
        completionHandler: @escaping (URL?) -> Void
    ) {
        let downloads = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
        let safeName = URL(fileURLWithPath: suggestedFilename).lastPathComponent.isEmpty
            ? "HIQS-download"
            : URL(fileURLWithPath: suggestedFilename).lastPathComponent
        let safeURL = URL(fileURLWithPath: safeName)
        let stem = safeURL.deletingPathExtension().lastPathComponent
        let fileExtension = safeURL.pathExtension
        var destination = downloads.appendingPathComponent(safeName)
        var suffix = 2
        while FileManager.default.fileExists(atPath: destination.path) {
            let nextName = fileExtension.isEmpty
                ? "\(stem)-\(suffix)"
                : "\(stem)-\(suffix).\(fileExtension)"
            destination = downloads.appendingPathComponent(nextName)
            suffix += 1
        }
        completionHandler(destination)
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)

let menu = NSMenu()
let appMenuItem = NSMenuItem()
menu.addItem(appMenuItem)
let appMenu = NSMenu()
appMenu.addItem(withTitle: "退出 HIQS", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
appMenuItem.submenu = appMenu
application.mainMenu = menu
application.run()
