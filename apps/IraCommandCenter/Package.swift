// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "IraCommandCenter",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "IraCommandCenter", targets: ["IraCommandCenter"]),
    ],
    targets: [
        .executableTarget(name: "IraCommandCenter"),
    ]
)
