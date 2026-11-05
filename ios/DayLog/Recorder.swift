import AVFoundation
import CoreLocation

/// Schrijft audiobuffers naar AAC-bestanden en knipt elke `chunkSeconds` een nieuw bestand.
/// Wordt alleen vanuit de audio-tap aangeroepen (één thread), dus geen locks nodig.
final class ChunkWriter {
    private let format: AVAudioFormat
    private let framesPerChunk: AVAudioFramePosition
    private let store: ChunkStore
    private let location: () -> CLLocation?
    private let onChunkReady: () -> Void

    private var file: AVAudioFile?
    private var current: ChunkMeta?
    private var framesWritten: AVAudioFramePosition = 0

    init(format: AVAudioFormat, chunkSeconds: Double, store: ChunkStore,
         location: @escaping () -> CLLocation?, onChunkReady: @escaping () -> Void) {
        self.format = format
        self.framesPerChunk = AVAudioFramePosition(format.sampleRate * chunkSeconds)
        self.store = store
        self.location = location
        self.onChunkReady = onChunkReady
    }

    func write(_ buffer: AVAudioPCMBuffer) {
        if file == nil { open() }
        guard let file else { return }
        do {
            try file.write(from: buffer)
            framesWritten += AVAudioFramePosition(buffer.frameLength)
        } catch {
            finish()
            return
        }
        if framesWritten >= framesPerChunk { finish() }
    }

    func finish() {
        guard let meta = current else { return }
        file = nil  // dealloc sluit het bestand en schrijft de AAC-header
        current = nil
        framesWritten = 0
        store.complete(meta.id)
        onChunkReady()
    }

    private func open() {
        let meta = store.begin(location: location())
        // AAC, mono, lage bitrate: ~15 MB per uur en hardware-encoded (zuinig).
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: format.sampleRate,
            AVNumberOfChannelsKey: format.channelCount,
            AVEncoderBitRateKey: 32_000,
        ]
        do {
            file = try AVAudioFile(
                forWriting: store.partialURL(meta.id), settings: settings,
                commonFormat: format.commonFormat, interleaved: format.isInterleaved
            )
            current = meta
        } catch {
            store.delete(meta.id)
        }
    }
}

/// Neemt op met AVAudioEngine zolang de toggle aan staat, ook als de app op de achtergrond is.
final class Recorder: ObservableObject {
    @Published private(set) var isRecording = false
    @Published private(set) var lastError: String?

    var chunkSeconds: Double = 300
    var location: () -> CLLocation? = { nil }
    var onChunkReady: () -> Void = {}

    private let engine = AVAudioEngine()
    private var writer: ChunkWriter?
    private var wantsRecording = false

    init() {
        let nc = NotificationCenter.default
        nc.addObserver(self, selector: #selector(handleInterruption(_:)),
                       name: AVAudioSession.interruptionNotification, object: nil)
        nc.addObserver(self, selector: #selector(handleConfigChange(_:)),
                       name: .AVAudioEngineConfigurationChange, object: engine)
        nc.addObserver(self, selector: #selector(handleMediaReset(_:)),
                       name: AVAudioSession.mediaServicesWereResetNotification, object: nil)
    }

    func setEnabled(_ enabled: Bool) {
        wantsRecording = enabled
        enabled ? start() : stop()
    }

    private func start() {
        guard !engine.isRunning else { return }
        do {
            let session = AVAudioSession.sharedInstance()
            // mixWithOthers: muziek/podcasts blijven spelen. Geen .allowBluetooth (HFP), anders
            // pakt iOS de AirPods-mic en zakt de muziekkwaliteit; we gebruiken de iPhone-mic.
            try session.setCategory(.playAndRecord, mode: .default,
                                    options: [.mixWithOthers, .allowBluetoothA2DP, .defaultToSpeaker])
            try session.setActive(true)

            let input = engine.inputNode
            let format = input.outputFormat(forBus: 0)
            let writer = ChunkWriter(format: format, chunkSeconds: chunkSeconds, store: .shared,
                                     location: location, onChunkReady: onChunkReady)
            self.writer = writer
            input.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, _ in
                writer.write(buffer)
            }
            engine.prepare()
            try engine.start()
            publish(recording: true, error: nil)
        } catch {
            engine.inputNode.removeTap(onBus: 0)
            publish(recording: false, error: error.localizedDescription)
        }
    }

    private func stop() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        writer?.finish()  // tap is weg, dus geen race met de audio-thread
        writer = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        publish(recording: false, error: nil)
    }

    private func restartIfWanted() {
        stop()
        if wantsRecording { start() }
    }

    private func publish(recording: Bool, error: String?) {
        DispatchQueue.main.async {
            self.isRecording = recording
            self.lastError = error
        }
    }

    // Telefoongesprek, Siri, wekker: iOS stopt de engine. Daarna weer oppakken.
    @objc private func handleInterruption(_ note: Notification) {
        guard let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
              let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
        switch type {
        case .began:
            stop()
        case .ended:
            if wantsRecording { start() }
        @unknown default:
            break
        }
    }

    // Route-wissel (koptelefoon in/uit) kan het inputformaat veranderen: opnieuw opbouwen.
    @objc private func handleConfigChange(_ note: Notification) { restartIfWanted() }
    @objc private func handleMediaReset(_ note: Notification) { restartIfWanted() }
}
