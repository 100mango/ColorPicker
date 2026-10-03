import SwiftUI

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
                    Text("Celluloid、QRCatcher 和 TouchColor 在设备本地处理照片、相机画面、二维码或颜色数据，开发者不收集或上传这些数据。用户主动分享、打开链接，以及系统 iCloud 同步等行为由相应服务处理。如有隐私问题，请联系 100mango@gmail.com。你可以删除应用内记录，在系统设置撤回权限；删除应用会清除其本地数据，照片图库及系统备份需另行管理。")
                    Text("Celluloid, QRCatcher, and TouchColor process photos, camera images, QR codes, or color data locally on your device. The developer does not collect or upload this data. Actions you choose to take, such as sharing or opening links, and system services such as iCloud sync are handled by the respective services. For privacy questions, contact 100mango@gmail.com. You can delete records in the apps and revoke permissions in system settings. Deleting an app clears its local data; your photo library and system backups must be managed separately.")
                    Link("Published privacy policy", destination: URL(string: "https://100mango.github.io/app-privacy/")!)
                    Link("100mango@gmail.com", destination: URL(string: "mailto:100mango@gmail.com")!)
                }.textSelection(.enabled)
            }
        }.padding(24).frame(width: 600, height: 540)
    }
}
