import Foundation

final class APIClient {
    static let shared = APIClient()
    private let session: URLSession
    private let baseURL: String
    
    init(baseURL: String = "http://localhost:8000", session: URLSession = .shared) {
        self.baseURL = baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        self.session = session
    }
    
    var wsURL: String {
        let b = baseURL
        if b.hasPrefix("http://") {
            return "ws://" + b.dropFirst(7) + "/api/ws/stream"
        }
        if b.hasPrefix("https://") {
            return "wss://" + b.dropFirst(8) + "/api/ws/stream"
        }
        return "ws://" + b + "/api/ws/stream"
    }
    
    func url(_ path: String) -> URL? {
        let p = path.hasPrefix("/") ? path : "/" + path
        return URL(string: baseURL + p)
    }
    
    func fetch<T: Decodable>(_ path: String) async throws -> T {
        guard let u = url(path) else { throw URLError(.badURL) }
        let (data, res) = try await session.data(from: u)
        guard let http = res as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
    
    func fetchAgents() async throws -> AgentsResponse {
        try await fetch("/api/agents")
    }
    
    func fetchEndocrine() async throws -> EndocrineResponse {
        try await fetch("/api/endocrine")
    }
    
    func fetchPipelineTimings(limit: Int = 24) async throws -> PipelineTimingsResponse {
        try await fetch("/api/pipeline/timings?limit=\(limit)")
    }
    
    func fetchDeepHealth() async throws -> DeepHealthResponse {
        try await fetch("/api/deep-health")
    }
    
    func fetchTerminalMetrics() async throws -> TerminalMetricsResponse {
        try await fetch("/api/terminal/metrics")
    }
    
    func fetchCrmList(limit: Int = 200) async throws -> CRMListResponse {
        try await fetch("/api/crm/list?limit=\(limit)")
    }
}
