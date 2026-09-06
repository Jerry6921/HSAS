import AppKit
import Foundation
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSWindow?
    private var webView: WKWebView?
    private var backend: Process?
    private var outputPipe: Pipe?
    private var outputBuffer = Data()
    private var backendURL: URL?

    func applicationDidFinishLaunching(_ notification: Notification) {
        createWindow()
        startBackend()
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        outputPipe?.fileHandleForReading.readabilityHandler = nil
        if let process = backend, process.isRunning {
            process.terminate()
            process.waitUntilExit()
        }
    }

    private func createWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = self

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
        let executable = resources.appendingPathComponent("backend/hiqs-backend")
        let browserRoot = resources.appendingPathComponent("playwright-browsers")
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            showStartupError("HIQS 后端文件不存在或无法执行。")
            return
        }

        let process = Process()
        let pipe = Pipe()
        process.executableURL = executable
        process.arguments = ["ui", "--port", "0", "--no-open"]
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
            try process.run()
            backend = process
            outputPipe = pipe
        } catch {
            showStartupError("HIQS 后端无法启动：\(error.localizedDescription)")
        }
    }

    private func consumeBackendOutput(_ data: Data) {
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
        if url.host == "127.0.0.1" || url.scheme == "about" {
            decisionHandler(.allow)
            return
        }
        if url.scheme == "http" || url.scheme == "https" {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
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
