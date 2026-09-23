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
    var beginNavigation: (() -> Void)?
    private var provisionalNavigation = false

    static func startsNewDocument(current: URL?, target: URL?, type: WKNavigationType,
                                  method: String?, provisional: Bool) -> Bool {
        if target?.scheme?.lowercased() == "javascript" { return false }
        // A reload, form submission or an in-flight full navigation must not be
        // mistaken for an anchor change, including redirects to a fragment URL.
        guard !provisional, type != .reload, type != .formSubmitted,
              type != .formResubmitted, (method ?? "GET").uppercased() == "GET",
              let current, let target,
              var from = URLComponents(url: current, resolvingAgainstBaseURL: true),
              var to = URLComponents(url: target, resolvingAgainstBaseURL: true),
              from.percentEncodedFragment != to.percentEncodedFragment else { return true }
        from.fragment = nil
        to.fragment = nil
        // Compare every remaining component (including credentials and query),
        // not a URL prefix or just the path. An identical URL is still a reload.
        return from != to
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        provisionalNavigation = true
    }

    func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) {
        provisionalNavigation = false
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if navigationAction.targetFrame?.isMainFrame == true,
           Self.startsNewDocument(current: webView.url, target: navigationAction.request.url,
                                  type: navigationAction.navigationType,
                                  method: navigationAction.request.httpMethod,
                                  provisional: provisionalNavigation) {
            provisionalNavigation = true
            beginNavigation?()
        }
        decisionHandler(.allow)
    }

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
        provisionalNavigation = false
        finish(.failure(HelperError(code: "webpage.navigation_failed", message: error.localizedDescription)))
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        provisionalNavigation = false
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

    @MainActor
    static func metadata(from webView: WKWebView) async throws -> (String, String) {
        #if QUASI_WEBPAGE_TESTING
        if ProcessInfo.processInfo.environment["QUASI_WEBPAGE_TEST_STALL"] == "metadata" {
            await withCheckedContinuation { (_: CheckedContinuation<Void, Never>) in }
        }
        #endif
        let script = "JSON.stringify({title: document.title || '', site: (document.querySelector('meta[property=\\\"og:site_name\\\"]') || {}).content || ''})"
        // The callback API is available on macOS 11; its async overlay is 12+.
        let raw: String = try await withCheckedThrowingContinuation { continuation in
            webView.evaluateJavaScript(script, in: nil, in: .defaultClient) { result in
                if let value = try? result.get() as? String {
                    continuation.resume(returning: value)
                } else {
                    continuation.resume(throwing: HelperError(
                        code: "webpage.metadata_failed", message: "could not evaluate page metadata"
                    ))
                }
            }
        }
        guard let data = raw.data(using: .utf8),
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

    static func stabilizationMilliseconds(_ name: String, production: Int) -> Int {
        #if QUASI_WEBPAGE_TESTING
        if let raw = ProcessInfo.processInfo.environment["QUASI_WEBPAGE_TEST_STABILIZE_" + name + "_MS"],
           let value = Int(raw), value >= 0 {
            return value
        }
        #endif
        return production
    }

    // evaluateJavaScript can itself stall. A local timer bounds that await;
    // both callbacks run on the main actor and only the first resumes it.
    @MainActor
    final class FingerprintSample {
        private var continuation: CheckedContinuation<String, Error>?

        func read(_ webView: WKWebView, script: String, budget: UInt64) async throws -> String {
            try await withCheckedThrowingContinuation { continuation in
                self.continuation = continuation
                let timeout = DispatchWorkItem {
                    self.finish(.failure(HelperError(
                        code: "webpage.stabilization_failed", message: "fingerprint deadline exceeded"
                    )))
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(Int(budget)), execute: timeout)
                #if QUASI_WEBPAGE_TESTING
                if ProcessInfo.processInfo.environment["QUASI_WEBPAGE_TEST_STALL"] == "fingerprint" {
                    return // Exercise the local timer without a JavaScript callback.
                }
                #endif
                webView.evaluateJavaScript(script, in: nil, in: .defaultClient) { result in
                    let value = try? result.get()
                    timeout.cancel()
                    if let value = value as? String {
                        self.finish(.success(value))
                    } else {
                        self.finish(.failure(HelperError(
                            code: "webpage.stabilization_failed", message: "invalid fingerprint"
                        )))
                    }
                }
            }
        }

        private func finish(_ result: Result<String, Error>) {
            guard let continuation else { return }
            self.continuation = nil
            continuation.resume(with: result)
        }
    }

    // Only the native owner holds authoritative network state. The random token
    // and captured message function remain in the document-start closure.
    @MainActor
    final class NetworkActivity: NSObject, WKScriptMessageHandler {
        let name = "quasi" + UUID().uuidString.replacingOccurrences(of: "-", with: "")
        private(set) var token = UUID().uuidString
        var pending = Set<String>()
        var seen = Set<String>()
        var revision = 0
        var documentID = ""
        var ready = false
        func beginNavigation(_ controller: WKUserContentController? = nil) {
            // Rotate the native secret before allowing a main-frame navigation.
            // Old documents cannot supply this generation, even with queued init.
            token = UUID().uuidString
            ready = false; documentID = ""
            pending.removeAll(); seen.removeAll(); revision += 1
            if let controller {
                controller.removeAllUserScripts()
                let tracker = WebpageCapture.networkTracker
                    .replacingOccurrences(of: "__HANDLER__", with: name)
                    .replacingOccurrences(of: "__TOKEN__", with: token)
                controller.addUserScript(WKUserScript(source: tracker,
                    injectionTime: .atDocumentStart, forMainFrameOnly: true, in: .page))
            }
        }

        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let body = message.body as? [String: String] else { return }
            receive(body, mainFrame: message.frameInfo.isMainFrame)
        }

        func receive(_ body: [String: String], mainFrame: Bool) {
            guard mainFrame, body["token"] == token,
                  let action = body["action"], let id = body["id"], !id.isEmpty else { return }
            if action == "init" {
                guard !ready else { return }
                documentID = id
                pending.removeAll(); seen.removeAll(); ready = true; revision += 1
            } else if !ready || !id.hasPrefix(documentID + ":") {
                return // A queued message from the previous document is stale.
            } else if action == "start", seen.insert(id).inserted {
                pending.insert(id); revision += 1
            } else if action == "settle", pending.remove(id) != nil {
                revision += 1
            }
        }
    }

    static let networkTracker = """
    (() => {
      const apply = Reflect.apply;
      const define = Object.defineProperty;
      const then = Promise.prototype.then;
      const clone = Response.prototype.clone;
      const body = Object.getOwnPropertyDescriptor(Response.prototype, 'body').get;
      const getReader = ReadableStream.prototype.getReader;
      const read = ReadableStreamDefaultReader.prototype.read;
      const add = EventTarget.prototype.addEventListener;
      const remove = EventTarget.prototype.removeEventListener;
      const handler = window.webkit.messageHandlers.__HANDLER__;
      const post = handler.postMessage;
      const token = '__TOKEN__';
      const epoch = crypto.getRandomValues(new Uint32Array(4)).join('-');
      let serial = 0;
      const sendMessage = (action, id) => apply(post, handler, [{token, action, id}]);
      sendMessage('init', epoch);
      const begin = () => {
        const id = epoch + ':' + (++serial);
        sendMessage('start', id);
        let settled = false;
        return () => { if (!settled) { settled = true; sendMessage('settle', id); } };
      };
      const fetch = window.fetch;
      define(window, 'fetch', {configurable: false, writable: false, value: function(...args) {
        const settle = begin();
        try {
          return apply(then, apply(fetch, this, args), [response => {
            try {
              const stream = apply(body, apply(clone, response, []), []);
              if (!stream) { settle(); return response; }
              const reader = apply(getReader, stream, []);
              const drain = () => {
                try { apply(then, apply(read, reader, []), [part => {
                  if (part.done) settle(); else drain();
                }, settle]); } catch (_) { settle(); }
              };
              drain();
            } catch (_) { settle(); }
            return response;
          }, error => { settle(); throw error; }]);
        } catch (error) { settle(); throw error; }
      }});
      const xhr = XMLHttpRequest;
      const send = xhr.prototype.send;
      define(xhr.prototype, 'send', {configurable: false, writable: false, value: function(...args) {
        const settle = begin();
        const done = event => {
          if (event && !event.isTrusted) return;
          try { apply(remove, this, ['loadend', done]); } finally { settle(); }
        };
        try {
          apply(add, this, ['loadend', done]);
          return apply(send, this, args);
        } catch (error) { try { done(); } finally { throw error; } }
      }});
      define(window, 'XMLHttpRequest', {value: xhr, configurable: false, writable: false});
    })();
    """

    @MainActor
    static func stabilize(_ webView: WKWebView, network: NetworkActivity) async throws {
        let minimum = stabilizationMilliseconds("MIN", production: 1500)
        let quiet = stabilizationMilliseconds("QUIET", production: 600)
        let maximum = stabilizationMilliseconds("MAX", production: 5000)
        let poll = max(1, stabilizationMilliseconds("POLL", production: 200))
        func now() -> UInt64 { DispatchTime.now().uptimeNanoseconds / 1_000_000 }
        let started = now()
        var changed = started
        var previous: String?
        var networkChanged = started
        var previousNetwork: String?
        var lastSampleValid = false
        var archiveSafe = false
        #if QUASI_WEBPAGE_TESTING
        var fingerprintAttempts = 0
        #endif
        // Only a small fingerprint crosses the WebKit boundary, never the DOM itself.
        let script = """
        (() => {
          const dom = document.documentElement ? document.documentElement.outerHTML : '';
          let hash = 2166136261;
          for (let i = 0; i < dom.length; i++) {
            hash = Math.imul(hash ^ dom.charCodeAt(i), 16777619) >>> 0;
          }
          const incomplete = Array.from(document.images).filter(i => !i.complete).length;
          const fonts = document.fonts ? document.fonts.status : 'unsupported';
          return JSON.stringify({href: location.href, ready: document.readyState,
            hash: hash, length: dom.length, body: !!document.body, images: document.images.length, text: document.body ? document.body.innerText.length : 0,
            resources: performance.getEntriesByType('resource').length,
            incomplete: incomplete, fonts: fonts});
        })()
        """
        repeat {
            do {
                let elapsed = now() - started
                let budget = UInt64(maximum) > elapsed ? UInt64(maximum) - elapsed : 1
                #if QUASI_WEBPAGE_TESTING
                fingerprintAttempts += 1
                if fingerprintAttempts > 1 && ProcessInfo.processInfo.environment["QUASI_WEBPAGE_TEST_STALL"] == "after-first-fingerprint" {
                    throw HelperError(code: "webpage.stabilization_failed", message: "injected later sample failure")
                }
                #endif
                let sample = try await FingerprintSample().read(webView, script: script, budget: budget)
                guard let data = sample.data(using: .utf8),
                      let values = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let ready = values["ready"] as? String,
                      let incomplete = values["incomplete"] as? Int,
                      let fonts = values["fonts"] as? String,
                      let resources = values["resources"] as? Int,
                      let images = values["images"] as? Int, network.ready else {
                    throw HelperError(code: "webpage.stabilization_failed", message: "invalid stabilization sample")
                }
                lastSampleValid = true
                archiveSafe = ready == "complete" && incomplete == 0 && fonts != "loading"
                    && !webView.isLoading && network.pending.isEmpty
                // Resource/network activity has its own mandatory quiet window.
                // Unlike DOM churn, it may never be waived at the local bound.
                let networkSample = "\(network.revision):\(network.pending.count):\(resources):\(images):\(incomplete):\(fonts):\(ready):\(webView.isLoading)"
                if networkSample != previousNetwork { networkChanged = now() }
                previousNetwork = networkSample
                if sample != previous { changed = now() }
                previous = sample
                if now() - started >= UInt64(minimum), archiveSafe,
                   now() - changed >= UInt64(quiet), now() - networkChanged >= UInt64(quiet) { return }
            } catch {
                // A transient navigation/context failure breaks the quiet window.
                lastSampleValid = false
                previous = nil
                changed = now()
                previousNetwork = nil
                networkChanged = now()
            }
            let elapsed = now() - started
            if elapsed >= UInt64(maximum) { break }
            let remaining = UInt64(maximum) - elapsed
            try await Task.sleep(nanoseconds: min(UInt64(poll), remaining) * 1_000_000)
        } while true
        guard lastSampleValid && archiveSafe && network.ready && network.pending.isEmpty && !webView.isLoading
            && now() - networkChanged >= UInt64(quiet) else {
            throw HelperError(code: "webpage.stabilization_failed", message: "could not sample page during stabilization")
        }
        // Only DOM churn may bypass quiet at the local bound. The existing
        // native total deadline remains armed throughout sampling and serialization.
    }

    @MainActor
    static func loadOnce(url: URL, staging: URL?, descriptor: Int32?) async throws -> ResultPayload {
        #if QUASI_WEBPAGE_TESTING
        if ProcessInfo.processInfo.environment["QUASI_WEBPAGE_TEST_STALL"] == "parent" {
            if let staging { try Data("partial staging".utf8).write(to: staging) }
            await withCheckedContinuation { (_: CheckedContinuation<Void, Never>) in }
        }
        #endif
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = WKWebsiteDataStore.nonPersistent()
        let network = NetworkActivity()
        configuration.userContentController.add(network, contentWorld: .page, name: network.name)
        network.beginNavigation(configuration.userContentController)
        let webView = WKWebView(frame: .zero, configuration: configuration)
        let observer = NavigationObserver()
        observer.beginNavigation = { network.beginNavigation(configuration.userContentController) }
        webView.navigationDelegate = observer
        try await observer.load(URLRequest(url: url), in: webView)
        try await stabilize(webView, network: network)
        guard let finalURL = webView.url?.absoluteString else {
            throw HelperError(code: "webpage.navigation_failed", message: "page did not provide a final URL")
        }
        let (title, site) = try await metadata(from: webView)
        if let staging {
            let archive = try await webArchive(from: webView)
            guard let descriptor, descriptor >= 0 else {
                throw HelperError(code: "webpage.capture_failed", message: "owned staging descriptor required")
            }
            guard ftruncate(descriptor, 0) == 0, lseek(descriptor, 0, SEEK_SET) >= 0 else {
                throw HelperError(code: "webpage.capture_failed", message: "cannot prepare staging descriptor")
            }
            try FileHandle(fileDescriptor: descriptor, closeOnDealloc: false).write(contentsOf: archive)
            guard fsync(descriptor) == 0 else {
                throw HelperError(code: "webpage.capture_failed", message: "cannot sync staging descriptor")
            }
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
    @MainActor
    static func runNetworkProtocolTest() {
        let current = URL(string: "https://example.org:443/page?q=1#old")!
        func classify(_ target: String, _ type: WKNavigationType = .other,
                      _ method: String = "GET", _ provisional: Bool = false) -> Bool {
            NavigationObserver.startsNewDocument(current: current, target: URL(string: target),
                type: type, method: method, provisional: provisional)
        }
        precondition(!classify("https://example.org:443/page?q=1#new"))
        precondition(!classify("https://example.org:443/page?q=1"))
        precondition(!classify("javascript:void(0)"))
        precondition(classify(current.absoluteString))
        precondition(classify("https://example.org:443/page?q=1#new", .reload))
        precondition(classify("https://example.org:443/page?q=1#new", .formSubmitted, "POST"))
        precondition(classify("https://example.org:443/page?q=1#new", .other, "GET", true))
        for target in ["http://example.org:443/page?q=1#new", "https://other.org:443/page?q=1#new",
                       "https://example.org:444/page?q=1#new", "https://example.org:443/other?q=1#new",
                       "https://example.org:443/page?q=2#new"] {
            precondition(classify(target))
        }
        let state = NetworkActivity()
        func message(_ token: String, _ action: String, _ id: String) {
            state.receive(["token": token, "action": action, "id": id], mainFrame: true)
        }
        state.beginNavigation()
        let a = state.token
        message(a, "init", "A"); message(a, "start", "A:1")
        precondition(state.ready && state.pending == ["A:1"])
        state.beginNavigation()
        let b = state.token
        precondition(a != b && !state.ready && state.pending.isEmpty && state.documentID.isEmpty)
        let resetRevision = state.revision
        for action in ["start", "settle", "init"] { message(a, action, "A:1") }
        precondition(!state.ready && state.pending.isEmpty && state.revision == resetRevision)
        message(b, "start", "B:1") // No activity accepted before this generation's init.
        precondition(state.pending.isEmpty)
        message(b, "init", "B"); message(b, "start", "B:1")
        let activeRevision = state.revision
        for action in ["start", "settle", "init"] { message(a, action, "A:1") }
        message(b, "init", "forged-replacement")
        precondition(state.ready && state.documentID == "B" && state.pending == ["B:1"]
                     && state.revision == activeRevision)
        message(b, "settle", "B:1"); message(b, "settle", "B:1")
        message(b, "start", "B:1")
        precondition(state.pending.isEmpty && state.revision == activeRevision + 1)
        print("network protocol PASS")
    }

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
        if arguments.count == 2 && arguments[1] == "network-protocol" {
            runNetworkProtocolTest()
            return
        }
        if arguments.count == 2 && arguments[1] == "terminal-race" {
            runTerminalRace()
            return
        }
        #endif
        guard arguments.count == 3 || arguments.count == 5 else {
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
        guard (mode == "inspect" && arguments.count == 3) || (mode == "capture" && arguments.count == 5) else {
            emit(ErrorPayload(code: "webpage.invalid_arguments", message: "capture requires one staging path"))
            exit(2)
        }
        let parent = getppid()
        let stagingPath = mode == "capture" ? arguments[3] : nil
        let parentWatch = DispatchSource.makeTimerSource(queue: .global())
        parentWatch.schedule(deadline: .now(), repeating: .milliseconds(100))
        parentWatch.setEventHandler {
            if parent <= 1 || getppid() != parent {
                if let stagingPath { try? FileManager.default.removeItem(atPath: stagingPath) }
                exit(1)
            }
        }
        parentWatch.resume()
        defer { parentWatch.cancel() }
        let terminal = TerminalArbiter()
        let timeout = timeoutWorkItem(terminal)
        do {
            let staging = mode == "capture" ? URL(fileURLWithPath: arguments[3]) : nil
            let result = try await loadOnce(url: url, staging: staging, descriptor: mode == "capture" ? Int32(arguments[4]) : nil)
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
