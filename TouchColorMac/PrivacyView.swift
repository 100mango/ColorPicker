import SwiftUI
import AppKit

enum PrivacyPolicyCopy {
    static let simplifiedChinese = "Celluloid、QRCatcher 和 TouchColor 在设备本地处理照片、相机画面、二维码或颜色数据，开发者不收集或上传这些数据。用户主动分享、打开链接，以及系统 iCloud 同步等行为由相应服务处理。如有隐私问题，请联系 100mango@gmail.com。本地数据可通过相应应用或系统删除，权限可在系统设置中撤回。"
    static let english = "Celluloid, QRCatcher, and TouchColor process photos, camera images, QR codes, or color data locally on your device. The developer does not collect or upload this data. Actions you choose to take, such as sharing or opening links, and system services such as iCloud sync are handled by the respective services. For privacy questions, contact 100mango@gmail.com. Local data can be deleted through the relevant app or system, and permissions can be revoked in system settings."
}

/// Native, offline copy of the approved bilingual policy. No remote page is loaded automatically.
struct PrivacyView: View {
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Privacy Policy / 应用隐私政策").font(.title2)
                Spacer()
                Button("Close") { dismiss() }.keyboardShortcut(.cancelAction).accessibilityIdentifier("privacy.close")
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    SelectablePrivacyText(text: NSLocalizedString(PrivacyPolicyCopy.simplifiedChinese, comment: "Approved offline privacy policy"),
                        identifier: "privacy.policy.zh-Hans", label: NSLocalizedString("Privacy policy in Simplified Chinese", comment: "Privacy paragraph accessibility"))
                        .frame(maxWidth: .infinity, alignment: .leading)
                    SelectablePrivacyText(text: NSLocalizedString(PrivacyPolicyCopy.english, comment: "Approved offline privacy policy"),
                        identifier: "privacy.policy.en", label: NSLocalizedString("Privacy policy in English", comment: "Privacy paragraph accessibility"))
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Link("Published privacy policy", destination: URL(string: "https://100mango.github.io/app-privacy/")!)
                    Link("100mango@gmail.com", destination: URL(string: "mailto:100mango@gmail.com")!)
                        .accessibilityLabel("Contact the developer about privacy")
                        .accessibilityIdentifier("privacy.contact")
                }.textSelection(.enabled)
            }
        }.padding(24).frame(width: 600, height: 540)
            .accessibilityElement(children: .contain)
            .accessibilityLabel("Privacy Policy / 应用隐私政策")
            .accessibilityIdentifier("privacy.content")
    }
}


/// App-owned selectable plain text avoids duplicate automatically detected email links.
/// The two explicit SwiftUI Links remain the only policy/contact actions.
struct SelectablePrivacyText: NSViewRepresentable {
    let text: String
    let identifier: String
    let label: String

    func makeNSView(context: Context) -> ParagraphTextView {
        ParagraphTextView(text: text, identifier: identifier, label: label)
    }
    func updateNSView(_ view: ParagraphTextView, context: Context) {
        view.update(text: text, identifier: identifier, label: label)
    }
    func sizeThatFits(_ proposal: ProposedViewSize, nsView: ParagraphTextView, context: Context) -> CGSize? {
        guard let width = proposal.width else { return nil }
        return nsView.measuredSize(width: width)
    }

    final class ParagraphTextView: NSTextView {
        init(text: String, identifier: String, label: String) {
            let storage = NSTextStorage()
            let manager = NSLayoutManager()
            let container = NSTextContainer(size: NSSize(width: 0, height: .greatestFiniteMagnitude))
            storage.addLayoutManager(manager)
            manager.addTextContainer(container)
            super.init(frame: .zero, textContainer: container)
            isEditable = false
            isSelectable = true
            isRichText = false
            isAutomaticLinkDetectionEnabled = false
            isAutomaticDataDetectionEnabled = false
            enabledTextCheckingTypes = 0
            drawsBackground = false
            textContainerInset = .zero
            container.lineFragmentPadding = 0
            container.lineBreakMode = .byWordWrapping
            container.widthTracksTextView = true
            container.heightTracksTextView = false
            isHorizontallyResizable = false
            isVerticallyResizable = false
            font = NSFont.preferredFont(forTextStyle: .body)
            textColor = .labelColor
            update(text: text, identifier: identifier, label: label)
        }
        required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

        func update(text: String, identifier: String, label: String) {
            if accessibilityIdentifier() != identifier { setAccessibilityIdentifier(identifier) }
            if accessibilityLabel() != label { setAccessibilityLabel(label) }
            // Unrelated SwiftUI updates must not clear the user's selected range.
            guard string != text else { return }
            string = text
            // Plain attributes only. No inline link ranges are authored or retained.
            textStorage?.setAttributes([.font: NSFont.preferredFont(forTextStyle: .body),
                                        .foregroundColor: NSColor.labelColor],
                                       range: NSRange(location: 0, length: (text as NSString).length))
        }
        func measuredSize(width: CGFloat) -> CGSize? {
            guard width.isFinite, width > 0, let liveContainer = textContainer,
                  let liveStorage = textStorage, let font else { return nil }
            // SwiftUI can probe several widths and choose an earlier result.
            // Speculative layout must never alter the displayed container or selection.
            let storage = NSTextStorage(attributedString: liveStorage)
            let manager = NSLayoutManager()
            let container = NSTextContainer(size: NSSize(width: width, height: .greatestFiniteMagnitude))
            container.lineFragmentPadding = liveContainer.lineFragmentPadding
            container.lineBreakMode = liveContainer.lineBreakMode
            storage.addLayoutManager(manager)
            manager.addTextContainer(container)
            manager.ensureLayout(for: container)
            let height = ceil(max(manager.usedRect(for: container).height,
                                  manager.defaultLineHeight(for: font)))
            guard height.isFinite, height > 0 else { return nil }
            return CGSize(width: width, height: height)
        }
    }
}
