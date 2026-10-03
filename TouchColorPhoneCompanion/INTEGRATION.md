# Explicit Watch inbox integration

These two UIKit/WatchConnectivity source files are prepared for the iOS/iPad owner; they are not yet members of the shipped iOS app target and have not run on iPhone.

- Add both `.swift` files to the existing TouchColor app target and link the local `ColorDomain` and `ColorPaletteLegacy` products. Keep iOS deployment at 15 and existing Objective-C source/store interfaces.
- In the application launch lifecycle, import the generated `TouchColor-Swift.h` and call `[[TCWatchPaletteInbox sharedInbox] activate]` on the main thread.
- Add a visible, accessible `Watch Inbox` action (identifier `watch.inbox.open`) to the home/palette workspace and call `[[TCWatchPaletteInbox sharedInbox] presentInboxFrom:self completion:^{ /* release sourceFlowActive exactly once */ }]`. Own the source/modal camera suspension through the existing controller coordinator. The callback is idempotent for Done, interactive dismissal and programmatic sheet removal; use a weak owner capture. Empty/error text is a self-sizing, scrollable table row, including at 320-point widths and accessibility text sizes.
- Localize the new UI strings in English/Simplified Chinese. Keep the existing privacy text unchanged.
- Receiving only stages the complete bounded version-1 request. Add Colors is an explicit append preserving `colorArray`, lowercase order/duplicates and the once-only `colorArrayRecoveryBackup`. No automatic phone/watch sync occurs.
- Receipt SHA-256 is of the canonical bounded request. Accepted and rejected duplicate delivery returns the saved outcome receipt without another append; a conflicting ID is rejected. On the Watch, only a matching UUID/fingerprint acknowledgement clears the persisted request. A lost acknowledgement is recovered by explicit Retry with the same UUID.
- No new entitlement, App Group, CloudKit, identifier registration or credential is required by these source edits. Watch signing/distribution remains unconfigured.

Required foreground runtime gate: use supported `simctl pair` with discovered iPhone/Watch simulator IDs, install the actual two app targets, then exercise Watch selection -> explicit Send -> pending request -> actual phone inbox -> explicit Add Colors -> receipt -> both app relaunches. Verify order/duplicates and the original recovery backup. If simulator transport fails, preserve the exact framework/system result; do not substitute a synthetic direct call for transport success.


Simulator transport boundary: Apple explicitly excludes `transferUserInfo` and WCSessionFile reception from Simulator. Test only the production foreground `sendMessage` path with both paired apps active/reachable; it stages the same immutable message and sends a matching acceptance receipt. A passing foreground test does not certify queued background delivery. Physical paired iPhone/Watch testing remains required for that path. Sources: https://developer.apple.com/documentation/watchconnectivity/wcsession/transferuserinfo(_:), https://developer.apple.com/documentation/watchconnectivity/wcsessiondelegate/session(_:didreceive:).
