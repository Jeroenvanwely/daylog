import CoreLocation
import Foundation

/// Metadata die met een chunk mee gaat. Staat als JSON-sidecar naast het audiobestand,
/// zodat een upload ook na een app-herstart nog weet wanneer en waar hij is opgenomen.
struct ChunkMeta: Codable {
    let id: UUID
    let startedAt: Date
    let lat: Double?
    let lon: Double?
}

/// Lokale buffer: `<id>.partial` tijdens opnemen, `<id>.m4a` als hij klaar is voor upload.
final class ChunkStore {
    static let shared = ChunkStore()

    let dir: URL
    private let fm = FileManager.default

    private init() {
        dir = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("chunks", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    func partialURL(_ id: UUID) -> URL { dir.appendingPathComponent("\(id.uuidString).partial") }
    func audioURL(_ id: UUID) -> URL { dir.appendingPathComponent("\(id.uuidString).m4a") }
    func metaURL(_ id: UUID) -> URL { dir.appendingPathComponent("\(id.uuidString).json") }

    func begin(location: CLLocation?) -> ChunkMeta {
        let meta = ChunkMeta(
            id: UUID(), startedAt: Date(),
            lat: location?.coordinate.latitude, lon: location?.coordinate.longitude
        )
        if let data = try? JSONEncoder().encode(meta) {
            try? data.write(to: metaURL(meta.id), options: .atomic)
        }
        return meta
    }

    /// Markeer een chunk als compleet (bestand is gesloten).
    func complete(_ id: UUID) {
        try? fm.moveItem(at: partialURL(id), to: audioURL(id))
    }

    func readyChunks() -> [ChunkMeta] {
        let files = (try? fm.contentsOfDirectory(atPath: dir.path)) ?? []
        return files
            .filter { $0.hasSuffix(".m4a") }
            .compactMap { UUID(uuidString: String($0.dropLast(4))) }
            .compactMap { id in
                guard let data = try? Data(contentsOf: metaURL(id)) else { return nil }
                return try? JSONDecoder().decode(ChunkMeta.self, from: data)
            }
            .sorted { $0.startedAt < $1.startedAt }
    }

    func delete(_ id: UUID) {
        for url in [audioURL(id), partialURL(id), metaURL(id)] { try? fm.removeItem(at: url) }
    }

    /// Een .partial die bij het starten nog bestaat is afgebroken (app gekilld): de AAC-container
    /// is dan niet afgesloten en onleesbaar, dus weg ermee.
    func cleanupOrphans() {
        let files = (try? fm.contentsOfDirectory(atPath: dir.path)) ?? []
        for name in files where name.hasSuffix(".partial") {
            if let id = UUID(uuidString: String(name.dropLast(8))) { delete(id) }
        }
    }
}
