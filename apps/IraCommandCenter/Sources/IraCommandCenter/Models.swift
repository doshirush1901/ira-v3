// Codable models for Ira API responses (Command Center).

import Foundation

// MARK: - Agents
struct AgentsResponse: Codable {
    let agents: [AgentRow]
    let count: Int
}

struct AgentRow: Codable, Identifiable {
    let name: String
    let role: String
    let description: String
    var power_level: Int?
    var tier: String?
    var tool_success_rate: Double?

    var id: String { name }
}

// MARK: - Endocrine
struct EndocrineResponse: Codable {
    let confidence: Double?
    let energy: Double?
    let growth_signal: Double?
    let stress: Double?
    let caution: Double?
    let boredom: Double?
    
    var levels: [(String, Double)] {
        [
            ("confidence", confidence ?? 0),
            ("energy", energy ?? 0),
            ("stress", stress ?? 0),
            ("caution", caution ?? 0),
            ("boredom", boredom ?? 0),
        ]
    }
}

// MARK: - Pipeline timings
struct PipelineTimingsResponse: Codable {
    let timings: [StageTimingRun]
}

struct StageTimingRun: Codable {
    let stages: [String: Double]?
    let timestamp: Double?
}

// MARK: - Deep health
struct DeepHealthResponse: Codable {
    let status: String?
    let services: [String: ServiceHealth]?
}

struct ServiceHealth: Codable {
    let status: String?
    let detail: String?
    
    var isHealthy: Bool {
        (status ?? "").lowercased() == "healthy" || (status ?? "").lowercased() == "ok" || (status ?? "").lowercased() == "connected"
    }
}

// MARK: - Terminal metrics
struct TerminalMetricsResponse: Codable {
    let pipeline: PipelineSummary?
    let active_campaigns: Int?
    let stale_leads: [StaleLead]?
    let recent_interactions: [RecentInteraction]?
}

struct StaleLead: Codable {
    let name: String?
    let email: String?
    let company_name: String?
    let company: String?  // fallback if API sends "company"
    
    var companyDisplay: String? { company_name ?? company }
}

struct PipelineSummary: Codable {
    let stages: [String: StageSummary]?
    let total_count: Int?
    let total_value: Double?
}

struct StageSummary: Codable {
    let count: Int?
    let total_value: Double?
}

struct RecentInteraction: Codable {
    let id: String?
    let created_at: String?
    let channel: String?
    let direction: String?
    let contact_id: String?
}

// MARK: - CRM list (deals with contact + company)
struct CRMListResponse: Codable {
    let deals: [CrmDeal]
    let count: Int
}

struct CrmDeal: Codable, Identifiable {
    let id: String
    let title: String?
    let stage: String?
    let value: Double?
    let currency: String?
    let machine_model: String?
    let created_at: String?
    let updated_at: String?
    let contact_id: String?
    let contact_name: String?
    let contact_email: String?
    let company_name: String?
}

// MARK: - WebSocket event (DataEventBus)
struct DataEventPayload: Codable {
    let ts: String?
    let type: String?
    let entity_type: String?
    let entity_id: String?
    let source_store: String?
    let payload_keys: [String]?
}
