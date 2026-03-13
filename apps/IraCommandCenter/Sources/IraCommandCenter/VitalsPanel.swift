import SwiftUI
import Charts

private struct VitalLevel: Identifiable {
    let id: String
    let name: String
    let value: Double
}

struct VitalsPanel: View {
    let endocrine: EndocrineResponse?
    let timings: [StageTimingRun]?
    let health: DeepHealthResponse?
    
    private var levelRows: [VitalLevel] {
        guard let e = endocrine, !e.levels.isEmpty else { return [] }
        return e.levels.prefix(5).map { VitalLevel(id: $0.0, name: $0.0, value: $0.1) }
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Vitals").font(.system(.headline, design: .monospaced)).foregroundStyle(.secondary)
            
            if !levelRows.isEmpty {
                Chart(levelRows) { row in
                    BarMark(
                        x: .value("Level", row.value),
                        y: .value("Metric", row.name)
                    )
                    .foregroundStyle(row.value > 0.6 ? Color.orange.opacity(0.9) : Color.green.opacity(0.9))
                }
                .chartXScale(domain: 0...1)
                .chartXAxis { AxisMarks(values: [0, 0.5, 1]) { _ in
                    AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(Color.white.opacity(0.1))
                    AxisValueLabel().font(.system(size: 9, design: .monospaced)).foregroundStyle(.secondary)
                }}
                .chartYAxis { AxisMarks(values: .automatic) { _ in
                    AxisValueLabel().font(.system(size: 9, design: .monospaced)).foregroundStyle(.secondary)
                }}
                .frame(height: 100)
            }
            
            if let last = timings?.first, let stages = last.stages, !stages.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Pipeline (ms)").font(.system(.caption2, design: .monospaced)).foregroundStyle(.tertiary)
                    HStack(spacing: 8) {
                        ForEach(Array(stages.sorted(by: { $0.key < $1.key })).prefix(6), id: \.key) { key, val in
                            Text("\(key): \(Int(val * 1000))").font(.system(.caption2, design: .monospaced)).foregroundStyle(.blue)
                        }
                    }
                }
            }
            
            if let svc = health?.services {
                HStack(spacing: 10) {
                    ForEach(Array(svc.keys.sorted()), id: \.self) { key in
                        let h = svc[key] ?? ServiceHealth(status: nil, detail: nil)
                        Circle()
                            .fill(h.isHealthy ? Color.green : Color.red)
                            .frame(width: 6, height: 6)
                        Text(key).font(.system(.caption2, design: .monospaced)).foregroundStyle(.secondary)
                    }
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
