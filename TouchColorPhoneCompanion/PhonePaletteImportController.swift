import UIKit
import UniformTypeIdentifiers
import ColorDomain
import ColorPaletteLegacy

/// Explicit file/paste review: the saved palette changes only after Add Colors.
@objc(TCPaletteImportController)
@MainActor final class PhonePaletteImportController: UITableViewController, UIDocumentPickerDelegate, UIAdaptivePresentationControllerDelegate {
    private let defaults: UserDefaults
    private let gate = CaptureEpoch()
    private let queue: OperationQueue = { let queue = OperationQueue(); queue.maxConcurrentOperationCount = 1; return queue }()
    private var providerProgress: Progress?
    private(set) var selection: PaletteSelection?
    private var source = ""
    private(set) var status = NSLocalizedString("Choose a JSON file or paste a JSON palette, then review every color before adding it.", comment: "Palette import help")
    private var busy = false
    private var completion: (() -> Void)?
    private var finished = false
    private var addButton: UIBarButtonItem!
    init(defaults: UserDefaults = .standard) { self.defaults = defaults; super.init(style: .insetGrouped) }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    @objc class func present(from owner: UIViewController, completion: @escaping () -> Void) {
        let content = PhonePaletteImportController(); content.completion = completion
        let navigation = UINavigationController(rootViewController: content); navigation.modalPresentationStyle = .pageSheet
        owner.present(navigation, animated: true) { navigation.presentationController?.delegate = content }
    }
    override func viewDidLoad() {
        super.viewDidLoad()
        title = NSLocalizedString("Import Palette", comment: "Palette import title")
        tableView.accessibilityIdentifier = "palette.import.review"
        tableView.rowHeight = UITableView.automaticDimension; tableView.estimatedRowHeight = 64
        pasteConfiguration = UIPasteConfiguration(acceptableTypeIdentifiers: [UTType.json.identifier, UTType.plainText.identifier])
        navigationItem.leftBarButtonItem = UIBarButtonItem(barButtonSystemItem: .cancel, target: self, action: #selector(close))
        navigationItem.leftBarButtonItem?.accessibilityIdentifier = "palette.import.close"
        addButton = UIBarButtonItem(title: NSLocalizedString("Add Colors", comment: "Palette import acceptance"), style: .done, target: self, action: #selector(accept))
        addButton.accessibilityIdentifier = "palette.import.accept"; navigationItem.rightBarButtonItem = addButton
        reload()
    }
    private func reload() { addButton?.isEnabled = !busy && !(selection?.colors.isEmpty ?? true); tableView.reloadData() }
    func begin() -> UInt64 {
        providerProgress?.cancel(); queue.cancelAllOperations(); busy = true
        status = NSLocalizedString("Reading palette…", comment: "Palette import status"); reload(); return gate.begin()
    }
    func apply(_ result: Result<PaletteSelection, Error>, name: String, token: UInt64) {
        guard gate.accepts(token) else { return }; busy = false
        switch result {
        case .success(let selected): selection = selected; source = name
            status = NSLocalizedString("Adding this selection appends every color in order. Existing colors and duplicates are kept.", comment: "Palette review")
        case .failure(let error): status = error.localizedDescription
        }
        reload()
    }
    func chooseFile() {
        _ = begin()
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.json], asCopy: false)
        picker.allowsMultipleSelection = false; picker.delegate = self; present(picker, animated: true)
    }
    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        guard urls.count == 1, let url = urls.first else { return }
        let token = begin(), epoch = gate
        let operation = BlockOperation()
        operation.addExecutionBlock { [weak self, weak operation] in
            let result = Result { try PaletteSelection.read(url, cancelled: { operation?.isCancelled != false || !epoch.accepts(token) }) }
            Task { @MainActor in self?.apply(result, name: url.lastPathComponent, token: token) }
        }
        queue.addOperation(operation)
    }
    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
        gate.invalidate(); providerProgress?.cancel(); queue.cancelAllOperations(); busy = false
        status = NSLocalizedString("Palette selection cancelled.", comment: "Palette import status"); reload()
    }
    override func paste(itemProviders: [NSItemProvider]) {
        let token = begin(), epoch = gate
        guard itemProviders.count == 1, let provider = itemProviders.first,
              let type = provider.registeredTypeIdentifiers.first(where: { UTType($0)?.conforms(to: .json) == true || UTType($0)?.conforms(to: .plainText) == true }) else {
            busy = false
            status = NSLocalizedString("Paste one JSON palette containing only #rrggbb colors.", comment: "Palette paste error"); reload(); return
        }
        providerProgress = provider.loadFileRepresentation(forTypeIdentifier: type) { [weak self] url, error in
            // Read the provider's scoped temporary file while this callback owns its lifetime.
            let result = Result { () throws -> PaletteSelection in
                guard let url else { throw error ?? PaletteFileError.invalid }
                return try PaletteSelection.read(url, cancelled: { !epoch.accepts(token) })
            }
            Task { @MainActor in self?.apply(result, name: NSLocalizedString("Pasted palette", comment: "Palette source"), token: token) }
        }
    }
    @objc private func accept() {
        guard !busy, let selection, !selection.colors.isEmpty else { return }
        busy = true; addButton.isEnabled = false
        LegacyPalette(defaults: defaults).append(selection.colors)
        close()
    }
    @objc private func close() { dismiss(animated: true) { self.finish() } }
    func presentationControllerDidDismiss(_ presentationController: UIPresentationController) { finish() }
    override func viewDidDisappear(_ animated: Bool) {
        super.viewDidDisappear(animated)
        if isBeingDismissed || navigationController?.isBeingDismissed == true { finish() }
    }
    private func finish() {
        guard !finished else { return }; finished = true
        gate.invalidate(); queue.cancelAllOperations(); providerProgress?.cancel()
        let callback = completion; completion = nil; callback?()
    }
    override func numberOfSections(in tableView: UITableView) -> Int { 3 }
    override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        section == 0 ? 2 : section == 1 ? 1 : (selection?.colors.count ?? 0)
    }
    override func tableView(_ tableView: UITableView, titleForHeaderInSection section: Int) -> String? {
        section == 2 && selection != nil ? source + " · " + String(format: NSLocalizedString("%ld selected colors", comment: "Palette count"), selection!.colors.count) : nil
    }
    override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = UITableViewCell(style: .subtitle, reuseIdentifier: nil)
        for label in [cell.textLabel, cell.detailTextLabel] { label?.numberOfLines = 0; label?.adjustsFontForContentSizeCategory = true }
        cell.textLabel?.font = .preferredFont(forTextStyle: .body); cell.detailTextLabel?.font = .preferredFont(forTextStyle: .caption1)
        if indexPath.section == 0 {
            if indexPath.row == 1, #available(iOS 16.0, *) {
                let control = UIPasteControl(configuration: .init()); control.target = self
                control.accessibilityIdentifier = "palette.import.paste"; control.translatesAutoresizingMaskIntoConstraints = false
                cell.contentView.addSubview(control)
                let margins = cell.contentView.layoutMarginsGuide
                NSLayoutConstraint.activate([control.leadingAnchor.constraint(equalTo: margins.leadingAnchor), control.topAnchor.constraint(equalTo: margins.topAnchor), control.bottomAnchor.constraint(equalTo: margins.bottomAnchor), control.heightAnchor.constraint(greaterThanOrEqualToConstant: 44)])
                cell.selectionStyle = .none
            } else {
                cell.textLabel?.text = NSLocalizedString(indexPath.row == 0 ? "Choose JSON File" : "Paste JSON", comment: "Palette import source")
                cell.accessibilityIdentifier = indexPath.row == 0 ? "palette.import.file" : "palette.import.paste"
                cell.accessoryType = .disclosureIndicator; cell.accessibilityTraits.insert(.button)
            }
        } else if indexPath.section == 1 {
            cell.textLabel?.text = status; cell.selectionStyle = .none; cell.accessibilityIdentifier = "palette.import.status"
        } else if let color = selection?.colors[indexPath.row] {
            cell.textLabel?.text = color.hex; cell.detailTextLabel?.text = color.rgbDescription
            cell.accessibilityIdentifier = "palette.import.color.\(indexPath.row)"; cell.selectionStyle = .none
        }
        return cell
    }
    override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        guard indexPath.section == 0 else { return }
        if indexPath.row == 0 { chooseFile() }
        else if #unavailable(iOS 16.0) { paste(itemProviders: UIPasteboard.general.itemProviders) }
    }
}
