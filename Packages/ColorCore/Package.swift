// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ColorCore",
    platforms: [.iOS(.v15), .macOS(.v13), .watchOS(.v9), .tvOS(.v17), .visionOS(.v1)],
    products: [
        .library(name: "ColorDomain", targets: ["ColorDomain"]),
        .library(name: "ColorRaster", targets: ["ColorRaster"]),
        .library(name: "ColorPaletteLegacy", targets: ["ColorPaletteLegacy"])
    ],
    targets: [
        .target(name: "ColorDomain"),
        .target(name: "ColorRaster", dependencies: ["ColorDomain"]),
        .target(name: "ColorPaletteLegacy", dependencies: ["ColorDomain"]),
        .testTarget(name: "ColorDomainTests", dependencies: ["ColorDomain"]),
        .testTarget(name: "ColorRasterTests", dependencies: ["ColorRaster"]),
        .testTarget(name: "ColorPaletteLegacyTests", dependencies: ["ColorPaletteLegacy"])
    ]
)
