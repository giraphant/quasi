import Foundation
import Speech
import AVFoundation
import CoreMedia

func srtTime(_ s: Double) -> String {
    let clamped = max(0, s)
    let total = Int(floor(clamped))
    let ms = Int((clamped - floor(clamped)) * 1000)
    return String(format: "%02d:%02d:%02d,%03d", total / 3600, (total % 3600) / 60, total % 60, ms)
}

func err(_ s: String) { FileHandle.standardError.write(Data((s + "\n").utf8)) }

@main
struct AppleSTT {
    static func main() async {
        let args = CommandLine.arguments
        guard args.count >= 2 else { err("usage: apple-stt <audiofile> [locale=en-US]"); exit(2) }
        let url = URL(fileURLWithPath: args[1])
        let localeId = args.count >= 3 ? args[2] : "en-US"
        let locale = Locale(identifier: localeId)

        do {
            let supported = await SpeechTranscriber.supportedLocales
            err("[apple-stt] locale=\(localeId) supported=\(supported.contains { $0.identifier(.bcp47) == locale.identifier(.bcp47) })")

            let transcriber = SpeechTranscriber(
                locale: locale,
                transcriptionOptions: [],
                reportingOptions: [],
                attributeOptions: [.audioTimeRange]
            )

            if let req = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
                err("[apple-stt] downloading model assets for \(localeId)…")
                try await req.downloadAndInstall()
            }

            let analyzer = SpeechAnalyzer(modules: [transcriber])
            let audioFile = try AVAudioFile(forReading: url)

            let collector = Task { () -> [(Double, Double, String)] in
                var cues: [(Double, Double, String)] = []
                for try await result in transcriber.results {
                    let text = String(result.text.characters).trimmingCharacters(in: .whitespacesAndNewlines)
                    if text.isEmpty { continue }
                    cues.append((result.range.start.seconds, result.range.end.seconds, text))
                }
                return cues
            }

            _ = try await analyzer.analyzeSequence(from: audioFile)
            try await analyzer.finalizeAndFinishThroughEndOfInput()
            let cues = try await collector.value

            var out = ""
            for (i, c) in cues.enumerated() {
                out += "\(i + 1)\n\(srtTime(c.0)) --> \(srtTime(c.1))\n\(c.2)\n\n"
            }
            FileHandle.standardOutput.write(Data(out.utf8))
            err("[apple-stt] done: \(cues.count) cues")
        } catch {
            err("[apple-stt] error: \(error)")
            exit(1)
        }
    }
}
