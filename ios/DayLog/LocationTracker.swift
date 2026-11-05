import CoreLocation

/// Grove locatie via significant-change monitoring: ~500 m nauwkeurig, nauwelijks batterij.
/// Ruim genoeg om "thuis" van "kantoor" te onderscheiden.
final class LocationTracker: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private let lock = NSLock()
    private var latest: CLLocation?

    var last: CLLocation? { lock.withLock { latest } }

    func start() {
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        manager.requestAlwaysAuthorization()
        manager.startMonitoringSignificantLocationChanges()
        manager.requestLocation()
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let loc = locations.last else { return }
        lock.withLock { latest = loc }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        // Geen locatie is geen probleem: de chunk gaat dan zonder plek.
    }
}
