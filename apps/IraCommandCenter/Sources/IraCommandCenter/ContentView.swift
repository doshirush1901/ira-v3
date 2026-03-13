import SwiftUI

private let kBaseURLKey = "IraCommandCenter.baseURL"
private let kDefaultBaseURL = "http://localhost:8001"
private let kLegacyDefaultBaseURL = "http://localhost:8000"

struct ContentView: View {
    @StateObject private var ws = WebSocketService()
    
    @AppStorage(kBaseURLKey) private var storedBaseURL = kDefaultBaseURL
    @State private var baseURL: String = ""
    @State private var agents: [AgentRow] = []
    @State private var endocrine: EndocrineResponse?
    @State private var timings: [StageTimingRun] = []
    @State private var health: DeepHealthResponse?
    @State private var pipeline: PipelineSummary?
    @State private var activeCampaigns = 0
    @State private var staleLeads: [StaleLead] = []
    @State private var recentInteractions: [RecentInteraction] = []
    @State private var crmDeals: [CrmDeal] = []
    @State private var lastError: String?
    @State private var timer: Timer?
    @State private var showSettings = false
    
    private var effectiveBaseURL: String {
        let u = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        return u.isEmpty ? kDefaultBaseURL : u
    }
    
    var body: some View {
        VStack(spacing: 0) {
            if let err = lastError {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Can't reach Ira API at \(effectiveBaseURL). Is the server running? Use the gear to set the correct base URL.")
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.orange)
                        Text(err)
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    Button("Dismiss") { lastError = nil }
                        .buttonStyle(.plain)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(Color.orange.opacity(0.12))
            }
            
            HSplitView {
                VStack(spacing: 10) {
                    PantheonPanel(agents: agents)
                        .frame(minHeight: 160, maxHeight: .infinity)
                    EventLedgerPanel(events: ws.events, status: ws.connectionStatus)
                        .frame(minHeight: 200, maxHeight: .infinity)
                }
                .frame(minWidth: 340, maxWidth: .infinity, maxHeight: .infinity)
                
                VStack(spacing: 10) {
                    VitalsPanel(endocrine: endocrine, timings: timings.isEmpty ? nil : timings, health: health)
                        .frame(minHeight: 140, maxHeight: .infinity)
                    CRMMetricsPanel(
                        pipeline: pipeline,
                        activeCampaigns: activeCampaigns,
                        staleLeads: staleLeads,
                        recentInteractions: recentInteractions.isEmpty ? nil : recentInteractions,
                        crmDeals: crmDeals.isEmpty ? nil : crmDeals
                    )
                    .frame(minHeight: 180, maxHeight: .infinity)
                }
                .frame(minWidth: 360, maxWidth: .infinity, maxHeight: .infinity)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(12)
        .background(Color(red: 0.04, green: 0.04, blue: 0.04))
        .preferredColorScheme(.dark)
        .font(.system(.body, design: .monospaced))
        .overlay(alignment: .topTrailing) {
            Button(action: { showSettings = true }) {
                Image(systemName: "gearshape")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .padding(12)
        }
        .onAppear {
            if baseURL.isEmpty {
                baseURL = storedBaseURL
                if baseURL.isEmpty { baseURL = kDefaultBaseURL }
            }
            if storedBaseURL == kLegacyDefaultBaseURL || baseURL == kLegacyDefaultBaseURL {
                storedBaseURL = kDefaultBaseURL
                baseURL = kDefaultBaseURL
            }
            startPolling()
            ws.connect(baseURL: effectiveBaseURL)
        }
        .onChange(of: baseURL) { _ in
            storedBaseURL = baseURL
            ws.connect(baseURL: effectiveBaseURL)
        }
        .onDisappear {
            timer?.invalidate()
            ws.disconnect()
        }
        .sheet(isPresented: $showSettings) {
            SettingsView(baseURL: $baseURL, defaultURL: kDefaultBaseURL)
        }
    }
    
    private func startPolling() {
        Task { @MainActor in await fetchAll() }
        timer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { _ in
            Task { @MainActor in await fetchAll() }
        }
        RunLoop.main.add(timer!, forMode: .common)
    }
    
    @MainActor
    private func fetchAll() async {
        let client = APIClient(baseURL: effectiveBaseURL)
        do {
            async let agentsRes: AgentsResponse = client.fetchAgents()
            async let endocrineRes: EndocrineResponse = client.fetchEndocrine()
            async let timingsRes: PipelineTimingsResponse = client.fetchPipelineTimings(limit: 1)
            async let healthRes: DeepHealthResponse = client.fetchDeepHealth()
            async let metricsRes: TerminalMetricsResponse = client.fetchTerminalMetrics()
            
            let (a, e, t, h, m) = try await (agentsRes, endocrineRes, timingsRes, healthRes, metricsRes)
            agents = a.agents
            endocrine = e
            timings = t.timings
            health = h
            pipeline = m.pipeline
            activeCampaigns = m.active_campaigns ?? 0
            staleLeads = m.stale_leads ?? []
            recentInteractions = m.recent_interactions ?? []
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
        // Fetch CRM list separately so one failure doesn't hide the list
        do {
            let crm = try await client.fetchCrmList(limit: 200)
            crmDeals = crm.deals
        } catch {
            crmDeals = []
        }
    }
}
