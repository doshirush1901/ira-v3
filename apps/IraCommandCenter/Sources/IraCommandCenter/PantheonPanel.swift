import SwiftUI

struct PantheonPanel: View {
    let agents: [AgentRow]
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Pantheon").font(.system(.headline, design: .monospaced)).foregroundStyle(.secondary)
            if agents.isEmpty {
                Text("No agents").font(.system(.body, design: .monospaced)).foregroundStyle(.tertiary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
            } else {
                Table(agents) {
                    TableColumn("Agent") { row in Text(row.name).font(.system(.body, design: .monospaced)) }
                    TableColumn("Role") { row in Text(row.role).font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary).lineLimit(1) }
                    TableColumn("Power") { row in Text(row.power_level.map { "\($0)" } ?? "—").font(.system(.body, design: .monospaced)).foregroundStyle(.orange) }
                    TableColumn("Tier") { row in Text(row.tier ?? "—").font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary) }
                    TableColumn("Tool %") { row in
                        if let r = row.tool_success_rate {
                            Text(String(format: "%.0f%%", r * 100)).font(.system(.body, design: .monospaced)).foregroundStyle(.green)
                        } else {
                            Text("—").font(.system(.body, design: .monospaced)).foregroundStyle(.tertiary)
                        }
                    }
                }
                .tableStyle(.bordered(alternatesRowBackgrounds: true))
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color(white: 0.08))
        .cornerRadius(8)
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.06), lineWidth: 1))
    }
}
