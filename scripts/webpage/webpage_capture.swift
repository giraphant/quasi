import Foundation
import WebKit

struct HelperError: Error {
    let code: String
    let message: String
}

struct ResultPayload: Codable {
    let status: String
    let final_url: String
    let title: String
    let site: String
    let staging_path: String?
}

struct ErrorPayload: Codable {
    let status: String
    let code: String
    let message: String

    init(code: String, message: String) {
        self.status = "failed"
        self.code = code
        self.message = message
    }
}

@MainActor
final class NavigationObserver: NSObject, WKNavigationDelegate {
    private var continuation: CheckedContinuation<Void, Error>?

    func load(_ request: URLRequest, in webView: WKWebView) async throws {
        guard continuation == nil else {
            throw HelperError(code: "webpage.navigation_failed", message: "navigation already active")
        }
        try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
            _ = webView.load(request)
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        finish(.success(()))
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        finish(.failure(HelperError(code: "webpage.navigation_failed", message: error.localizedDescription)))
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        finish(.failure(HelperError(code: "webpage.navigation_failed", message: error.localizedDescription)))
    }

    private func finish(_ result: Result<Void, Error>) {
        guard let continuation else { return }
        self.continuation = nil
        continuation.resume(with: result)
    }
}

@main
struct WebpageCapture {
    final class TerminalArbiter {
        private let lock = NSLock()
        private var settled = false

        func settle<T: Encodable>(_ payload: T, exitCode: Int) {
            lock.lock()
            guard !settled else {
                lock.unlock()
                return
            }
            settled = true
            lock.unlock()
            WebpageCapture.emit(payload)
            if exitCode != 0 {
                exit(Int32(exitCode))
            }
        }
    }

    static func emit<T: Encodable>(_ payload: T) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        FileHandle.standardOutput.write((try! encoder.encode(payload)))
        FileHandle.standardOutput.write(Data("\n".utf8))
    }

    static func metadata(from webView: WKWebView) async throws -> (String, String) {
        #if QUASI_WEBPAGE_TESTING
        if ProcessInfo.processInfo.environment["QUASI_WEBPAGE_TEST_STALL"] == "metadata" {
            await withCheckedContinuation { (_: CheckedContinuation<Void, Never>) in }
        }
        #endif
        let script = "JSON.stringify({title: document.title || '', site: (document.querySelector('meta[property=\\\"og:site_name\\\"]') || {}).content || ''})"
        guard let raw = try await webView.evaluateJavaScript(script) as? String,
              let data = raw.data(using: .utf8),
              let values = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let title = values["title"] as? String,
              let site = values["site"] as? String else {
            throw HelperError(code: "webpage.metadata_failed", message: "could not evaluate page metadata")
        }
        return (title, site)
    }

    @MainActor
    static func webArchive(from webView: WKWebView) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            webView.createWebArchiveData { result in
                continuation.resume(with: result)
            }
        }
    }

    @MainActor
    static func loadOnce(url: URL, staging: URL?) async throws -> ResultPayload {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = WKWebsiteDataStore.nonPersistent()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        let observer = NavigationObserver()
        webView.navigationDelegate = observer
        try await observer.load(URLRequest(url: url), in: webView)
        try await Task.sleep(nanoseconds: 750_000_000)
        guard let finalURL = webView.url?.absoluteString else {
            throw HelperError(code: "webpage.navigation_failed", message: "page did not provide a final URL")
        }
        let (title, site) = try await metadata(from: webView)
        if let staging {
            let archive = try await webArchive(from: webView)
            try archive.write(to: staging)
        }
        return ResultPayload(
            status: "complete",
            final_url: finalURL,
            title: title,
            site: site,
            staging_path: staging?.path
        )
    }

    static func deadlineMilliseconds() -> Int {
        #if QUASI_WEBPAGE_TESTING
        if let raw = ProcessInfo.processInfo.environment["QUASI_WEBPAGE_TEST_TIMEOUT_MS"],
           let milliseconds = Int(raw), milliseconds > 0 {
            return milliseconds
        }
        #endif
        return 60_000
    }

    static func timeoutWorkItem(_ terminal: TerminalArbiter) -> DispatchWorkItem {
        let timeout = DispatchWorkItem {
            terminal.settle(
                ErrorPayload(
                    code: "webpage.capture_timeout",
                    message: "page capture exceeded 60 seconds"
                ),
                exitCode: 1
            )
        }
        DispatchQueue.main.asyncAfter(
            deadline: .now() + .milliseconds(deadlineMilliseconds()),
            execute: timeout
        )
        return timeout
    }

    #if QUASI_WEBPAGE_TESTING
    static func runTerminalRace() {
        let terminal = TerminalArbiter()
        let contenders = DispatchGroup()
        let start = DispatchSemaphore(value: 0)
        contenders.enter()
        DispatchQueue.global().async {
            start.wait()
            terminal.settle(
                ResultPayload(
                    status: "complete",
                    final_url: "https://example.org/",
                    title: "Race success",
                    site: "example.org",
                    staging_path: nil
                ),
                exitCode: 0
            )
            contenders.leave()
        }
        contenders.enter()
        DispatchQueue.global().async {
            start.wait()
            terminal.settle(
                ErrorPayload(
                    code: "webpage.capture_timeout",
                    message: "page capture exceeded 60 seconds"
                ),
                exitCode: 1
            )
            contenders.leave()
        }
        start.signal()
        start.signal()
        contenders.wait()
        exit(0)
    }
    #endif

    static func main() async {
        let arguments = CommandLine.arguments
        #if QUASI_WEBPAGE_TESTING
        if arguments.count == 2 && arguments[1] == "terminal-race" {
            runTerminalRace()
            return
        }
        #endif
        guard arguments.count == 3 || arguments.count == 4 else {
            emit(ErrorPayload(code: "webpage.invalid_arguments", message: "usage: webpage_capture inspect URL | capture URL STAGING_PATH"))
            exit(2)
        }
        let mode = arguments[1]
        guard mode == "inspect" || mode == "capture",
              let url = URL(string: arguments[2]),
              let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https" else {
            emit(ErrorPayload(code: "webpage.invalid_url", message: "only HTTP and HTTPS URLs are supported"))
            exit(2)
        }
        guard (mode == "inspect" && arguments.count == 3) || (mode == "capture" && arguments.count == 4) else {
            emit(ErrorPayload(code: "webpage.invalid_arguments", message: "capture requires one staging path"))
            exit(2)
        }
        let terminal = TerminalArbiter()
        let timeout = timeoutWorkItem(terminal)
        do {
            let staging = mode == "capture" ? URL(fileURLWithPath: arguments[3]) : nil
            let result = try await loadOnce(url: url, staging: staging)
            timeout.cancel()
            terminal.settle(result, exitCode: 0)
        } catch let error as HelperError {
            timeout.cancel()
            terminal.settle(ErrorPayload(code: error.code, message: error.message), exitCode: 1)
        } catch {
            timeout.cancel()
            terminal.settle(
                ErrorPayload(code: "webpage.capture_failed", message: error.localizedDescription),
                exitCode: 1
            )
        }
    }
}
