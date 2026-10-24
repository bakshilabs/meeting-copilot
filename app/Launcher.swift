// Meeting Copilot.app: starts the copilot server, shows it in a window, stops it on quit.
import AppKit
import WebKit

let home = FileManager.default.homeDirectoryForCurrentUser.path
let projectDir = Bundle.main.object(forInfoDictionaryKey: "CopilotProjectDir") as? String ?? "\(home)/Projects/meeting-copilot"
let port = "8765"
let pageURL = URL(string: "http://127.0.0.1:\(port)")!

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?

    func applicationDidFinishLaunching(_ n: Notification) {
        buildMenu()
        let cfg = WKWebViewConfiguration()
        web = WKWebView(frame: .zero, configuration: cfg)
        web.uiDelegate = self
        web.loadHTMLString("<body style='font:15px -apple-system;color:#5b6472;display:grid;place-items:center;height:90vh'>Starting Meeting Copilot…</body>", baseURL: nil)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Meeting Copilot"
        window.contentView = web
        window.setFrameAutosaveName("MeetingCopilotMain")
        window.isReleasedWhenClosed = false
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startServer()
    }

    func startServer() {
        let logDir = "\(home)/Library/Logs"
        let logPath = "\(logDir)/MeetingCopilot.log"
        FileManager.default.createFile(atPath: logPath, contents: nil)
        let log = FileHandle(forWritingAtPath: logPath)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "\(projectDir)/run.sh")
        p.arguments = ["--no-browser", "--port", port]
        p.currentDirectoryURL = URL(fileURLWithPath: projectDir)
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "\(home)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        p.environment = env
        p.standardOutput = log
        p.standardError = log
        p.terminationHandler = { proc in
            DispatchQueue.main.async {
                if self.server === proc && !self.quitting {
                    self.web.loadHTMLString("<body style='font:15px -apple-system;padding:40px'>Meeting Copilot stopped unexpectedly. Details are in ~/Library/Logs/MeetingCopilot.log. Quit and reopen the app to try again.</body>", baseURL: nil)
                }
            }
        }
        do { try p.run(); server = p } catch {
            web.loadHTMLString("<body style='font:15px -apple-system;padding:40px'>Could not start: \(error.localizedDescription)</body>", baseURL: nil)
            return
        }
        waitForServer(tries: 240)
    }

    func waitForServer(tries: Int) {
        var req = URLRequest(url: pageURL); req.timeoutInterval = 1
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            DispatchQueue.main.async {
                if (resp as? HTTPURLResponse)?.statusCode == 200 { self.web.load(URLRequest(url: pageURL)) }
                else if tries > 0 { DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.waitForServer(tries: tries - 1) } }
            }
        }.resume()
    }

    var quitting = false
    func applicationWillTerminate(_ n: Notification) {
        quitting = true
        guard let p = server, p.isRunning else { return }
        p.interrupt()  // SIGINT lets the server stop audio capture and whisper cleanly
        let deadline = Date().addingTimeInterval(4)
        while p.isRunning && Date() < deadline { usleep(100_000) }
        if p.isRunning { p.terminate() }
        // Safety net for helper processes
        for pattern in ["\(projectDir)/bin/systap", "whisper-server -m .* --port 8178"] {
            let k = Process()
            k.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
            k.arguments = ["-f", pattern]
            try? k.run(); k.waitUntilExit()
        }
    }

    // Clicking the dock icon brings the window back.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil); return true
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    // Links (web sources) open in the default browser.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem(); main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Show Window", action: #selector(showWindow), keyEquivalent: "0")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Meeting Copilot", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let view = NSMenu(title: "View")
        view.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "r")
        viewItem.submenu = view
        NSApp.mainMenu = main
    }
    @objc func showWindow() { window.makeKeyAndOrderFront(nil) }
    @objc func reload() { web.load(URLRequest(url: pageURL)) }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
