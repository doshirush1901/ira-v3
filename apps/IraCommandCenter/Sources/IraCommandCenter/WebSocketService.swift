import Foundation

@MainActor
final class WebSocketService: ObservableObject {
    @Published private(set) var events: [DataEventPayload] = []
    @Published private(set) var isConnected = false
    @Published private(set) var connectionStatus: String = "Disconnected"
    
    private var task: Task<Void, Never>?
    private var wsTask: URLSessionWebSocketTask?
    private let maxEvents = 200
    private var reconnectDelay: UInt64 = 1
    
    func connect(baseURL: String) {
        disconnect()
        let wsURLString = APIClient(baseURL: baseURL).wsURL
        guard let url = URL(string: wsURLString) else {
            connectionStatus = "Invalid URL"
            return
        }
        connectionStatus = "Connecting..."
        task = Task {
            await run(url: url, baseURL: baseURL)
        }
    }
    
    func disconnect() {
        task?.cancel()
        task = nil
        wsTask?.cancel(with: .goingAway, reason: nil)
        wsTask = nil
        isConnected = false
        connectionStatus = "Disconnected"
    }
    
    private func run(url: URL, baseURL: String) async {
        let req = URLRequest(url: url)
        let ws = URLSession.shared.webSocketTask(with: req)
        wsTask = ws
        ws.resume()
        
        isConnected = true
        connectionStatus = "Connected"
        reconnectDelay = 1
        
        while !Task.isCancelled {
            do {
                let message = try await ws.receive()
                switch message {
                case .string(let s):
                    if let data = s.data(using: .utf8),
                       let evt = try? JSONDecoder().decode(DataEventPayload.self, from: data) {
                        events.insert(evt, at: 0)
                        if events.count > maxEvents {
                            events = Array(events.prefix(maxEvents))
                        }
                    }
                case .data(let data):
                    if let evt = try? JSONDecoder().decode(DataEventPayload.self, from: data) {
                        events.insert(evt, at: 0)
                        if events.count > maxEvents {
                            events = Array(events.prefix(maxEvents))
                        }
                    }
                @unknown default:
                    break
                }
            } catch {
                if !Task.isCancelled {
                    isConnected = false
                    connectionStatus = "Reconnecting..."
                    try? await Task.sleep(nanoseconds: reconnectDelay * 1_000_000_000)
                    reconnectDelay = min(reconnectDelay * 2, 30)
                    connect(baseURL: baseURL)
                }
                return
            }
        }
    }
}
