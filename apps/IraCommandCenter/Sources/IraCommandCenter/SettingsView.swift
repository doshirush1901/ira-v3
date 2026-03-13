import SwiftUI

struct SettingsView: View {
    @Binding var baseURL: String
    let defaultURL: String
    @Environment(\.dismiss) private var dismiss
    
    @State private var editedURL: String = ""
    
    var body: some View {
        VStack(spacing: 16) {
            Text("Settings")
                .font(.system(.headline, design: .monospaced))
            Text("Ira API base URL (REST and WebSocket)")
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
            TextField("http://localhost:8001", text: $editedURL)
                .textFieldStyle(.roundedBorder)
                .font(.system(.body, design: .monospaced))
            HStack {
                Button("Reset") {
                    editedURL = defaultURL
                }
                .buttonStyle(.bordered)
                Spacer()
                Button("Cancel") {
                    dismiss()
                }
                .buttonStyle(.bordered)
                Button("Done") {
                    let u = editedURL.trimmingCharacters(in: .whitespacesAndNewlines)
                    baseURL = u.isEmpty ? defaultURL : u
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding(24)
        .frame(width: 400)
        .onAppear {
            editedURL = baseURL.isEmpty ? defaultURL : baseURL
        }
    }
}
