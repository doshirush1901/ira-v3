import SwiftUI

struct EventLedgerPanel: View {
    let events: [DataEventPayload]
    let status: String
    
    private func color(for source: String?) -> Color {
        switch (source ?? "").lowercased() {
        case "neo4j": return .blue
        case "qdrant": return .purple
        case "crm": return .green
        default: return .secondary
        }
    }
    
    private func timeString(_ ts: String?) -> String {
        guard let ts = ts else { return "--:--:--" }
        if let d = ISO8601DateFormatter().date(from: ts) {
            let f = DateFormatter()
            f.dateFormat = "HH:mm:ss"
            return f.string(from: d)
        }
        return String(ts.prefix(8))
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Circulatory Ledger").font(.system(.headline, design: .monospaced)).foregroundStyle(.secondary)
                Spacer()
                Text(status).font(.system(.caption2, design: .monospaced))
                    .foregroundStyle(status == "Connected" ? .green : .orange)
            }
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 2) {
                        ForEach(Array(events.enumerated()), id: \.offset) { _, evt in
                            HStack(alignment: .top, spacing: 6) {
                                Text(timeString(evt.ts)).font(.system(.caption2, design: .monospaced)).foregroundStyle(.tertiary)
                                Text("[\(evt.source_store ?? "?")]").font(.system(.caption2, design: .monospaced))
                                    .foregroundStyle(color(for: evt.source_store))
                                Text(evt.type ?? "").font(.system(.caption2, design: .monospaced)).foregroundStyle(.secondary)
                                Text(evt.entity_type ?? "").font(.system(.caption2, design: .monospaced))
                                Text(evt.entity_id ?? "").font(.system(.caption2, design: .monospaced)).lineLimit(1).truncationMode(.tail)
                            }
                        }
                    }
                    .padding(4)
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color(white: 0.08))
        .cornerRadius(8)
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.06), lineWidth: 1))
    }
}
