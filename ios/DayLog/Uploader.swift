import Foundation

/// Uploadt complete chunks via een background URLSession: iOS maakt de upload af, ook als de
/// app gesuspendeerd is. Alleen via wifi. Bij een 2xx van de server gaat de lokale kopie weg.
final class Uploader: NSObject, URLSessionTaskDelegate {
    static let shared = Uploader()
    static let sessionID = "nl.vanwely.daylog.upload"

    /// Wordt door de AppDelegate gezet als iOS de app wekt voor afgeronde uploads.
    var backgroundCompletionHandler: (() -> Void)?

    private let store = ChunkStore.shared
    private let iso = ISO8601DateFormatter()

    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.background(withIdentifier: Self.sessionID)
        config.isDiscretionary = false
        config.sessionSendsLaunchEvents = true
        config.allowsExpensiveNetworkAccess = false  // geen mobiele data
        config.allowsConstrainedNetworkAccess = false  // niet in Low Data Mode
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    var serverURL: URL? {
        UserDefaults.standard.string(forKey: "serverURL").flatMap(URL.init(string:))
    }
    var token: String { UserDefaults.standard.string(forKey: "apiToken") ?? "" }

    func uploadPending() {
        guard let base = serverURL, !token.isEmpty else { return }
        session.getAllTasks { [self] tasks in
            let inFlight = Set(tasks.compactMap(\.taskDescription))
            for chunk in store.readyChunks() where !inFlight.contains(chunk.id.uuidString) {
                var req = URLRequest(url: base.appendingPathComponent("api/chunks"))
                req.httpMethod = "POST"
                req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                req.setValue("audio/mp4", forHTTPHeaderField: "Content-Type")
                req.setValue(chunk.id.uuidString, forHTTPHeaderField: "X-Chunk-Id")
                req.setValue(iso.string(from: chunk.startedAt), forHTTPHeaderField: "X-Started-At")
                if let lat = chunk.lat, let lon = chunk.lon {
                    req.setValue(String(lat), forHTTPHeaderField: "X-Lat")
                    req.setValue(String(lon), forHTTPHeaderField: "X-Lon")
                }
                let task = session.uploadTask(with: req, fromFile: store.audioURL(chunk.id))
                task.taskDescription = chunk.id.uuidString
                task.resume()
            }
        }
    }

    func pendingCount() -> Int { store.readyChunks().count }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    didCompleteWithError error: Error?) {
        guard error == nil,
              let http = task.response as? HTTPURLResponse,
              (200..<300).contains(http.statusCode),
              let id = task.taskDescription.flatMap(UUID.init(uuidString:)) else { return }
        store.delete(id)
        NotificationCenter.default.post(name: .chunkUploaded, object: nil)
    }

    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        DispatchQueue.main.async {
            self.backgroundCompletionHandler?()
            self.backgroundCompletionHandler = nil
        }
    }
}

extension Notification.Name {
    static let chunkUploaded = Notification.Name("chunkUploaded")
}
