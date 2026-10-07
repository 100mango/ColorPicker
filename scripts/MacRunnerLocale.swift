import Foundation

// Read-only host observation. This is not the app's effective locale.
let value: [String: Any] = [
    "localeIdentifier": Locale.current.identifier,
    "preferredLanguages": Locale.preferredLanguages
]
let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write(Data([10]))
