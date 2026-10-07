# TouchColor: later iOS + Watch package preparation

This additive projection is based on qualified original-iOS c66474316203ee4b29aab1d12ddaa20724b166ef. The existing TouchColor.xcodeproj, all original product sources, TouchColorWatch.xcodeproj, original archive workflow, signer and currently submitted IPA are unchanged. Nothing in this candidate replaces or withdraws the iOS submission.

## Exact integration

Run `python3 scripts/generate_ios_watch_project.py` locally to reproduce TouchColor-iOS-Watch.xcodeproj and its three Objective-C integration projections. Each projection is derived from a SHA-256-pinned current original input using fixed small replacements. The original AppDelegate gains the already-existing Inbox activation; ColorMainViewController and TCWorkspaceViewController regain the existing visible Watch Inbox action. A scoped category declaration exposes that action without changing the original header. All other iOS code, including current photo/import/lifecycle fixes, remains the original input. PhonePaletteInbox.swift, PhonePaletteInboxController.swift and the existing PhonePaletteImportController.swift are compiled once into the real shipping parent. No receiver, transport or data model is replaced; no automatic palette apply or photo save is added.

The new phone project restores one historical cross-project TouchColorWatch dependency and one Embed Watch Content phase. The Watch project, product and executable remain unchanged. The exact product set is TouchColor.app and TouchColor.app/Watch/TouchColor.app. Bundle identities are com.mango.touchColor and com.mango.touchColor.watchkitapp. Watch remains independent-capable with watchOS 9 floor; phone remains universal with iOS 15 floor. The existing unsupported-device Inbox status remains the iPad behavior; real iPad scope has not been rerun here.

Both products have the same executable name. The new phone target alone sets DWARF_DSYM_FILE_NAME=TouchColor-iOS.app.dSYM. The Watch retains TouchColor.app.dSYM. Verification binds each symbol file to its platform, architecture and actual UUID, so one product's dSYM cannot stand in for the other.

## One bounded archive candidate

The only new workflow is ios-watch-unsigned-archive.yml, triggered only by a push to codex/ios-watch-unsigned-archive. It has no simulator command, signing, export, portal access, provisioning update or retry. It uses the mature QR archive collector and owned process-group cleanup exactly, with one non-quiet xcodebuild archive command, 16 MiB full capture and at most 512 KiB retained prefix/tail output. Full captured logs are scanned for compiler errors before truncation. The original clock governs archive proof and evidence retention.

Archive policy fixes the two product paths, device platforms/slices, minimum OS, companion mode, metadata, source resources, privacy and both languages. The phone receiver/importer and WatchConnectivity linkage must actually exist. Matching per-product dSYM UUIDs and the actual Watch producer copy are checked. Exact copy is preferred; only the previously witnessed deterministic Release strip transform can explain an executable-only difference. Unknown code, profile, signing material, signature, test/harness product, symlink or extra application is rejected. Source identity before and after binds all original and added files to the exact reviewed Git tree and sole parent.

The original iOS tests remain useful only for their unchanged original project. Existing hosted/UI targets retained in the projection are not a claim that those tests qualify the new inbox entry, and the archive does not build or run them. Portable source/graph tests and synthetic archive negative tests do not prove live transfer or real UI behavior.

## Preserved evidence and remaining limits

The Watch product, local package inputs, Inbox implementations and Watch graph match the earlier 74cc source exactly. Its actual passed historical cases can be retained with that source identity. Touch saved-list Crown and Edit a Copy followed by delete/order are still unresolved. No runtime diagnosis or UI rerun is part of this package work, and archive success must not imply full product readiness. Live transfer, explicit phone apply/cancel, duplicate/relaunch preservation and iPad entry scope remain separate runtime evidence. Simulator limitations are not fabricated successes.

Current source versions remain 2.0 (20001) solely for a source-bound unsigned observation. Distribution needs a separately frozen unused successor, tentatively 2.1 (20002), synchronized across phone and Watch. No upload using the current version/build is authorized by this candidate. Watch Store assets and a separately reviewed exact signer/profile route remain open. Independent review and an exact-tree root GO are required before publication or a single native run.
