import SwiftUI
import UIKit

final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     handleEventsForBackgroundURLSession identifier: String,
                     completionHandler: @escaping () -> Void) {
        guard identifier == Uploader.sessionID else { return completionHandler() }
        Uploader.shared.backgroundCompletionHandler = completionHandler
    }
}

/// Verbindt recorder, locatie en uploader. Eén instantie voor de hele app.
final class AppModel: ObservableObject {
    let recorder = Recorder()
    let location = LocationTracker()
    @Published var pending = 0

    init() {
        ChunkStore.shared.cleanupOrphans()
        recorder.location = { [location] in location.last }
        recorder.onChunkReady = { [weak self] in
            Uploader.shared.uploadPending()
            self?.refresh()
        }
        NotificationCenter.default.addObserver(
            forName: .chunkUploaded, object: nil, queue: .main
        ) { [weak self] _ in self?.refresh() }
        location.start()
        refresh()
    }

    func refresh() {
        DispatchQueue.main.async { self.pending = Uploader.shared.pendingCount() }
    }
}

@main
struct DayLogApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .environmentObject(model.recorder)
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                Uploader.shared.uploadPending()
                model.refresh()
            }
        }
    }
}
