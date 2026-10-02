// Research-only local-file probe; never wired to Penny's ledger or delivery.
import Foundation
import Speech
import AVFoundation

@main
struct AppleSpeechProbe {
    static func main() async {
        do {
            let args = CommandLine.arguments
            let locale = Locale(identifier: "en-US")
            guard SpeechTranscriber.isAvailable,
                  let supported = await SpeechTranscriber.supportedLocale(equivalentTo: locale) else {
                throw NSError(domain: "probe", code: 1, userInfo: [NSLocalizedDescriptionKey: "speech_transcriber_unavailable"])
            }
            let transcriber = SpeechTranscriber(locale: supported,
                transcriptionOptions: [], reportingOptions: [], attributeOptions: [.audioTimeRange])
            let status = await AssetInventory.status(forModules: [transcriber])
            if args.count == 2 && args[1] == "--install-assets" {
                if let installation = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
                    try await installation.downloadAndInstall()
                }
                print("asset_status=\(await AssetInventory.status(forModules: [transcriber]))")
                return
            }
            if args.count == 1 {
                print("available=true asset_status=\(status) installed=\(await SpeechTranscriber.installedLocales.map(\.identifier).sorted()) legacy_authorization=\(SFSpeechRecognizer.authorizationStatus().rawValue)")
                return
            }
            guard status == .installed else {
                throw NSError(domain: "probe", code: 2, userInfo: [NSLocalizedDescriptionKey: "assets_not_installed"])
            }
            let started = Date()
            let file = try AVAudioFile(forReading: URL(fileURLWithPath: args[1]))
            let analyzer = SpeechAnalyzer(modules: [transcriber])
            let collector = Task { () throws -> [[String: Any]] in
                var segments: [[String: Any]] = []
                for try await result in transcriber.results {
                    segments.append(["text": String(result.text.characters),
                        "start": result.range.start.seconds,
                        "end": CMTimeRangeGetEnd(result.range).seconds])
                }
                return segments
            }
            do {
                if let end = try await analyzer.analyzeSequence(from: file) {
                    try await analyzer.finalizeAndFinish(through: end)
                } else {
                    try await analyzer.finalizeAndFinishThroughEndOfInput()
                }
                let segments = try await collector.value
                let payload: [String: Any] = ["engine": "apple-speechtranscriber", "locale": supported.identifier,
                    "elapsed_seconds": Date().timeIntervalSince(started), "segments": segments,
                    "text": segments.compactMap { $0["text"] as? String }.joined()]
                let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
                FileHandle.standardOutput.write(data)
                FileHandle.standardOutput.write(Data("\n".utf8))
            } catch {
                await analyzer.cancelAndFinishNow()
                collector.cancel()
                throw error
            }
        } catch {
            let e = error as NSError
            // Keep private paths/provider descriptions out of diagnostics.
            FileHandle.standardError.write(Data("probe_failed domain=\(e.domain) code=\(e.code)\n".utf8))
            exit(1)
        }
    }
}
