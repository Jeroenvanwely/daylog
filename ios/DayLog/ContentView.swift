import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var recorder: Recorder
    @AppStorage("recordingEnabled") private var enabled = false
    @AppStorage("serverURL") private var serverURL = ""
    @AppStorage("apiToken") private var apiToken = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Toggle(isOn: $enabled) {
                        Label(recorder.isRecording ? "Neemt op" : "Uit",
                              systemImage: recorder.isRecording ? "waveform" : "mic.slash")
                    }
                    .tint(.red)
                    if let error = recorder.lastError {
                        Text(error).font(.footnote).foregroundStyle(.red)
                    }
                } footer: {
                    Text("Zet uit bij klanten en waar anderen praten zonder jou.")
                }

                Section("Upload") {
                    LabeledContent("Wachtend op upload", value: "\(model.pending)")
                    Button("Nu uploaden") {
                        Uploader.shared.uploadPending()
                        model.refresh()
                    }
                    if let url = URL(string: serverURL), !serverURL.isEmpty {
                        Link("Logboek openen", destination: url)
                    }
                }

                Section("Server") {
                    TextField("https://mac.tailnet.ts.net", text: $serverURL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("API-token", text: $apiToken)
                }
            }
            .navigationTitle("DayLog")
        }
        .onAppear { recorder.setEnabled(enabled) }
        .onChange(of: enabled) { _, on in recorder.setEnabled(on) }
    }
}
