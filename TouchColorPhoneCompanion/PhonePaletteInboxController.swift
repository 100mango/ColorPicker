import UIKit
import ColorDomain

@MainActor final class PhonePaletteInboxController: UITableViewController, UIAdaptivePresentationControllerDelegate {
    private let inbox: PhonePaletteInbox
    private var messages: [PaletteTransfer] = []
    var onDismiss: (() -> Void)?
    private var didFinishDismissal = false
    private var statusText: String?
    private var observation: NSObjectProtocol?
    init(inbox: PhonePaletteInbox) { self.inbox = inbox; super.init(style: .insetGrouped) }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func viewDidLoad() {
        super.viewDidLoad()
        title = NSLocalizedString("Watch Inbox", comment: "Companion inbox")
        tableView.accessibilityIdentifier = "watch.inbox"
        navigationItem.rightBarButtonItem = UIBarButtonItem(barButtonSystemItem: .done, target: self, action: #selector(close))
        navigationItem.rightBarButtonItem?.accessibilityIdentifier = "watch.inbox.close"
        observation = NotificationCenter.default.addObserver(forName: .touchColorWatchInboxChanged, object: inbox, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.reload() }
        }
        reload()
    }
    deinit { if let observation { NotificationCenter.default.removeObserver(observation) } }
    @objc private func close() { dismiss(animated: true) { self.finishDismissal() } }
    func presentationControllerDidDismiss(_ presentationController: UIPresentationController) { finishDismissal() }
    override func viewDidDisappear(_ animated: Bool) {
        super.viewDidDisappear(animated)
        if isBeingDismissed || navigationController?.isBeingDismissed == true { finishDismissal() }
    }
    private func finishDismissal() {
        guard !didFinishDismissal else { return }
        didFinishDismissal = true; let completion = onDismiss; onDismiss = nil; completion?()
    }
    private func reload() {
        var readError: String?
        do { messages = try inbox.pending(); tableView.reloadData() }
        catch { readError = NSLocalizedString("The inbox could not be read. Its saved data was kept.", comment: "Companion inbox error") }
        statusText = readError ?? inbox.status ?? (messages.isEmpty ? NSLocalizedString("No pending Watch colors. Send selected colors from TouchColor on your paired Apple Watch.", comment: "Companion inbox empty") : nil)
        tableView.backgroundView = nil
        tableView.rowHeight = UITableView.automaticDimension; tableView.estimatedRowHeight = 80
        tableView.reloadData()
    }
    override func numberOfSections(in tableView: UITableView) -> Int { 2 }
    override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        section == 0 ? (statusText == nil ? 0 : 1) : messages.count
    }
    override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        if indexPath.section == 0 {
            let cell = UITableViewCell(style: .default, reuseIdentifier: nil)
            cell.textLabel?.text = statusText; cell.textLabel?.numberOfLines = 0
            cell.textLabel?.font = .preferredFont(forTextStyle: .body); cell.textLabel?.adjustsFontForContentSizeCategory = true
            cell.selectionStyle = .none; cell.accessibilityIdentifier = "watch.inbox.status"
#if DEBUG
            cell.accessibilityValue = inbox.pairedStatusValue
#endif
            return cell
        }
        let message = messages[indexPath.row]
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: nil)
        cell.textLabel?.text = String(format: NSLocalizedString("%ld selected colors", comment: "Companion inbox count"), message.colors.count)
        cell.detailTextLabel?.text = message.colors.map(\.hex).joined(separator: "  ")
        for label in [cell.textLabel, cell.detailTextLabel] { label?.numberOfLines = 0; label?.adjustsFontForContentSizeCategory = true }
        cell.textLabel?.font = .preferredFont(forTextStyle: .body)
        cell.detailTextLabel?.font = .preferredFont(forTextStyle: .caption1)
        cell.detailTextLabel?.textColor = .label
        cell.accessoryType = .disclosureIndicator; cell.accessibilityTraits.insert(.button); cell.accessibilityIdentifier = "watch.inbox.\(message.id.uuidString)"
#if DEBUG
        cell.accessibilityValue = inbox.pairedRequestValue(message.id)
#endif
        return cell
    }
    override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        guard indexPath.section == 1 else { return }
        let message = messages[indexPath.row]
        let alert = UIAlertController(title: NSLocalizedString("Add these colors?", comment: "Companion acceptance"),
            message: NSLocalizedString("These selected colors will be appended in order. Existing colors and duplicates are kept.", comment: "Companion acceptance"), preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: NSLocalizedString("Cancel", comment: "Companion acceptance"), style: .cancel))
        alert.addAction(UIAlertAction(title: NSLocalizedString("Add Colors", comment: "Companion acceptance"), style: .default) { [weak self] _ in
            do { try self?.inbox.accept(message.id); self?.reload() } catch { self?.show(error) }
        })
        alert.addAction(UIAlertAction(title: NSLocalizedString("Decline Transfer", comment: "Companion acceptance"), style: .destructive) { [weak self] _ in
            do { try self?.inbox.reject(message.id); self?.reload() } catch { self?.show(error) }
        })
        present(alert, animated: true)
    }
    private func show(_ error: Error) {
        let alert = UIAlertController(title: NSLocalizedString("Could Not Complete", comment: "Companion inbox error"), message: error.localizedDescription, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: NSLocalizedString("OK", comment: "Companion inbox error"), style: .cancel))
        if presentedViewController != nil {
            dismiss(animated: true) { [weak self] in self?.present(alert, animated: true) }
        } else { present(alert, animated: true) }
    }
}
