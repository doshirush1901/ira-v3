import SwiftUI
import Charts

private struct StageRow: Identifiable {
    let id: String
    let name: String
    let count: Int
    let value: Double
}

struct CRMMetricsPanel: View {
    let pipeline: PipelineSummary?
    let activeCampaigns: Int
    let staleLeads: [StaleLead]
    let recentInteractions: [RecentInteraction]?
    let crmDeals: [CrmDeal]?
    
    private var stageRows: [StageRow] {
        guard let stages = pipeline?.stages else { return [] }
        return stages.map { StageRow(id: $0.key, name: $0.key, count: $0.value.count ?? 0, value: $0.value.total_value ?? 0) }
            .sorted { $0.name < $1.name }
    }
    
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                Text("CRM & Metrics").font(.system(.headline, design: .monospaced)).foregroundStyle(.secondary)
            
            HStack(spacing: 20) {
                if let p = pipeline {
                    metricBlock("Pipeline value", value: String(format: "$%.0f", p.total_value ?? 0), color: .green)
                    metricBlock("Deals", value: "\(p.total_count ?? 0)", color: .primary)
                }
                metricBlock("Campaigns", value: "\(activeCampaigns)", color: .primary)
            }
            
            VStack(alignment: .leading, spacing: 4) {
                Text("CRM list — customers / leads / quotes").font(.system(.caption, design: .monospaced)).foregroundStyle(.tertiary)
                if let deals = crmDeals, !deals.isEmpty {
                    Table(deals) {
                        TableColumn("Company") { d in Text(d.company_name ?? "—").font(.system(.caption2, design: .monospaced)).lineLimit(1) }
                        TableColumn("Contact") { d in Text(d.contact_name ?? "—").font(.system(.caption2, design: .monospaced)).lineLimit(1) }
                        TableColumn("Stage") { d in Text(d.stage ?? "—").font(.system(.caption2, design: .monospaced)).foregroundStyle(.secondary) }
                        TableColumn("Value") { d in Text(String(format: "$%.0f", d.value ?? 0)).font(.system(.caption2, design: .monospaced)).foregroundStyle(.green) }
                        TableColumn("Updated") { d in Text(String((d.updated_at ?? "").prefix(10))).font(.system(.caption2, design: .monospaced)).foregroundStyle(.tertiary) }
                    }
                    .tableStyle(.bordered(alternatesRowBackgrounds: true))
                } else {
                    Text("No deals, or CRM list not loaded (check base URL and API).")
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
            }
            
            if !stageRows.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Pipeline by stage").font(.system(.caption, design: .monospaced)).foregroundStyle(.tertiary)
                    Chart(stageRows) { row in
                        BarMark(
                            x: .value("Value", row.value),
                            y: .value("Stage", row.name)
                        )
                        .foregroundStyle(Color.green.opacity(0.8))
                    }
                    .chartXAxis { AxisMarks(values: .automatic) { _ in
                        AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(Color.white.opacity(0.1))
                        AxisValueLabel().font(.system(size: 9, design: .monospaced)).foregroundStyle(.secondary)
                    }}
                    .chartYAxis { AxisMarks(values: .automatic) { _ in
                        AxisValueLabel().font(.system(size: 9, design: .monospaced)).foregroundStyle(.secondary)
                    }}
                    .frame(height: min(CGFloat(stageRows.count) * 20 + 20, 140))
                }
                
                Table(stageRows) {
                    TableColumn("Stage") { r in Text(r.name).font(.system(.caption2, design: .monospaced)) }
                    TableColumn("Cnt") { r in Text("\(r.count)").font(.system(.caption2, design: .monospaced)).foregroundStyle(.secondary) }
                    TableColumn("Value") { r in Text(String(format: "$%.0f", r.value)).font(.system(.caption2, design: .monospaced)).foregroundStyle(.green) }
                }
                .tableStyle(.bordered(alternatesRowBackgrounds: true))
            }
            
            if !staleLeads.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Stale leads (14d)").font(.system(.caption2, design: .monospaced)).foregroundStyle(.orange)
                    ForEach(Array(staleLeads.prefix(5).enumerated()), id: \.offset) { _, lead in
                        Text("\(lead.name ?? "?") — \(lead.email ?? "") \(lead.companyDisplay.map { "(\($0))" } ?? "")").font(.system(.caption2, design: .monospaced)).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
            }
            
            if let recent = recentInteractions, !recent.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Recent interactions").font(.system(.caption2, design: .monospaced)).foregroundStyle(.tertiary)
                    ForEach(Array(recent.prefix(5).enumerated()), id: \.offset) { _, ix in
                        HStack(spacing: 8) {
                            Text(ix.created_at?.prefix(19).description ?? "").font(.system(.caption2, design: .monospaced)).foregroundStyle(.tertiary)
                            Text(ix.channel ?? "").font(.system(.caption2, design: .monospaced))
                            Text(ix.direction ?? "").font(.system(.caption2, design: .monospaced)).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            }
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .padding(.bottom, 8)
        }
        .padding(10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color(white: 0.08))
        .cornerRadius(8)
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.06), lineWidth: 1))
    }
    
    private func metricBlock(_ label: String, value: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(label).font(.system(.caption2, design: .monospaced)).foregroundStyle(.tertiary)
            Text(value).font(.system(.body, design: .monospaced)).fontWeight(.medium).foregroundStyle(color)
        }
    }
}
