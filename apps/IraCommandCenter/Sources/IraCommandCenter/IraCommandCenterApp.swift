import SwiftUI

@main
struct IraCommandCenterApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
                .frame(minWidth: 800, minHeight: 600)
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1000, height: 700)
        .commands {
            CommandGroup(replacing: .newItem) {}
        }
    }
}
