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
        try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { continuation in
                self.continuation = continuation
                _ = webView.load(request)
            }
        }, onCancel: {
            Task { @MainActor in
                webView.stopLoading()
                self.finish(
                    .failure(
                        HelperError(
                            code: "webpage.capture_timeout",
                            message: "page capture exceeded 60 seconds"
                        )
                    )
                )
            }
        })
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
    static func emit<T: Encodable>(_ payload: T) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        FileHandle.standardOutput.write((try! encoder.encode(payload)))
        FileHandle.standardOutput.write(Data("\n".utf8))
    }

    static func metadata(from webView: WKWebView) async throws -> (String, String) {
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

    static func timedLoad(url: URL, staging: URL?) async throws -> ResultPayload {
        try await withThrowingTaskGroup(of: ResultPayload.self) { group in
            group.addTask { @MainActor in
                try await loadOnce(url: url, staging: staging)
            }
            group.addTask {
                try await Task.sleep(nanoseconds: 60_000_000_000)
                throw HelperError(code: "webpage.capture_timeout", message: "page capture exceeded 60 seconds")
            }
            guard let first = try await group.next() else {
                throw HelperError(code: "webpage.capture_failed", message: "page capture did not start")
            }
            group.cancelAll()
            return first
        }
    }

    static func main() async {
        let arguments = CommandLine.arguments
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
        do {
            let staging = mode == "capture" ? URL(fileURLWithPath: arguments[3]) : nil
            emit(try await timedLoad(url: url, staging: staging))
        } catch let error as HelperError {
            emit(ErrorPayload(code: error.code, message: error.message))
            exit(1)
        } catch {
            emit(ErrorPayload(code: "webpage.capture_failed", message: error.localizedDescription))
            exit(1)
        }
    }
}
