import SwiftUI
import AppKit

extension Color {
    static let brandNavy = Color(red: 0.043, green: 0.169, blue: 0.294)
    static let brandNavyDeep = Color(red: 0.027, green: 0.102, blue: 0.184)
    static let brandBlue = Color(red: 0.082, green: 0.365, blue: 0.937)
    static let brandCyan = Color(red: 0.220, green: 0.741, blue: 0.973)
    static let brandGold = Color(red: 0.788, green: 0.635, blue: 0.153)
}

let brandGradient = LinearGradient(
    colors: [.brandBlue, .brandCyan], startPoint: .leading, endPoint: .trailing)
let navyGradient = LinearGradient(
    colors: [.brandNavy, .brandNavyDeep],
    startPoint: .topLeading, endPoint: .bottomTrailing)

@main
struct MM1031App: App {
    @StateObject private var store = Store()

    var body: some Scene {
        WindowGroup("LeanFile") {
            ContentView()
                .environmentObject(store)
                .frame(minWidth: 980, minHeight: 600)
        }
        .windowStyle(.titleBar)

        Settings {
            SettingsView()
                .environmentObject(store)
        }

        MenuBarExtra("LeanFile", systemImage: "archivebox.fill") {
            Button(L.t("menu.open")) {
                NSApp.activate(ignoringOtherApps: true)
            }
            Divider()
            Text(L.f("menu.toreview", store.counts.inbox))
            Text(L.f("menu.files", store.counts.total))
            Divider()
            Button(L.t("menu.quit")) { NSApp.terminate(nil) }
        }
    }
}

enum Section: String, CaseIterable, Identifiable {
    case dashboard = "dashboard"
    case conversations = "conversations"
    case inbox = "inbox"
    case library = "library"
    case tags = "tags"
    case finals = "finals"
    case nodes = "nodes"
    case cleanup = "cleanup"
    case rules = "rules"
    case about = "about"
    var id: String { rawValue }
    var title: String { L.t("section." + key) }
    var key: String {
        switch self {
        case .dashboard: return "dashboard"
        case .conversations: return "conversations"
        case .inbox: return "inbox"
        case .library: return "library"
        case .tags: return "tags"
        case .finals: return "finals"
        case .nodes: return "nodes"
        case .cleanup: return "cleanup"
        case .rules: return "rules"
        case .about: return "about"
        }
    }
    var icon: String {
        switch self {
        case .dashboard: return "square.grid.2x2"
        case .conversations: return "text.bubble"
        case .inbox: return "tray.full"
        case .library: return "books.vertical"
        case .tags: return "tag.fill"
        case .finals: return "checkmark.seal"
        case .nodes: return "externaldrive.connected.to.line.below"
        case .cleanup: return "trash"
        case .rules: return "slider.horizontal.3"
        case .about: return "person.crop.circle"
        }
    }
}

@MainActor
final class Store: ObservableObject {
    @Published var section: Section = .dashboard
    @Published var assets: [AssetRow] = []
    @Published var dash = DashboardData()
    @Published var dashFiles: [AssetRow] = []
    @Published var timePreset: String = "all"
    @Published var selectedDay: String?
    @Published var dashTotal = 0
    @Published var drillTitle: String?
    @Published var drillFiles: [CollectionFile] = []
    @Published var detailShowsDrill = false
    @Published var rules: [String: String] = [:]
    @Published var cleanupPreview = (stale: 0, dedup: 0, ephemeral: 0)
    @Published var cleanupResult = ""
    @Published var actionMsg = ""
    @Published var nodes: [NodeRow] = []
    @Published var dups: [DupRow] = []
    @Published var conversationsList: [ConversationRow] = []
    @Published var selectedConversationId: String?
    @Published var langTick = 0
    @Published var counts = (inbox: 0, total: 0, finals: 0, dups: 0, convs: 0)
    @Published var selectedAssetId: String?
    @Published var versions: [VersionRow] = []
    @Published var locations: [(node: String, path: String)] = []
    @Published var preview = (thumb: "", excerpt: "", title: "")
    @Published var conversation = (tool: "", model: "", title: "", inferred: false, prompt: "")
    @Published var searchText: String = ""
    @Published var sortMode: String = "latest"
    @Published var tagFacets: [(dim: String, tag: String, count: Int)] = []
    @Published var selectedTags: Set<String> = []
    @Published var organizeResult: String = ""

    private var db: Database?
    // All database work runs on this serial queue, never on the main
    // thread: the UI must never freeze waiting for SQLite.
    private let queue = DispatchQueue(label: "tech.mm1031.store", qos: .userInitiated)
    private var searchWork: DispatchWorkItem?
    // Realtime sync: the watcher process updates the db file as new
    // files are ingested; poll its mtime and reload when it changes
    // (but never while a cleanup-type CLI operation is running).
    private var dbPath: String = ""
    private var lastDbMtime: TimeInterval = 0
    private var dbTimer: Timer?
    private var cliOpsInFlight = 0

    init() {
        let env = (ProcessInfo.processInfo.environment["MM1031_DB"] ?? ProcessInfo.processInfo.environment["GUICANG_DB"])
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let path = env ?? (home + "/mm1031-dev/ky-live.db")
        dbPath = path
        db = Database(path: path)
        lastDbMtime = Store.dbFileMtime(path)
        reload()
        dbTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.pollDbFile()
        }
    }

    private static func dbFileMtime(_ path: String) -> TimeInterval {
        var latest: TimeInterval = 0
        for p in [path, path + "-wal"] {
            if let attrs = try? FileManager.default.attributesOfItem(atPath: p),
               let d = attrs[.modificationDate] as? Date {
                latest = max(latest, d.timeIntervalSince1970)
            }
        }
        return latest
    }

    private func pollDbFile() {
        guard cliOpsInFlight == 0 else { return }
        let m = Store.dbFileMtime(dbPath)
        if m > lastDbMtime {
            lastDbMtime = m
            reload()
        }
    }

    static func rangeFor(preset: String, day: String?) -> (from: Double?, to: Double?) {
        let cal = Calendar.current
        let now = Date()
        if let day {
            let f = DateFormatter()
            f.dateFormat = "yyyy-MM-dd"
            if let d0 = f.date(from: day) {
                return (d0.timeIntervalSince1970,
                        d0.addingTimeInterval(86400).timeIntervalSince1970)
            }
        }
        switch preset {
        case "today":
            return (cal.startOfDay(for: now).timeIntervalSince1970, nil)
        case "week":
            return (cal.startOfDay(for: now.addingTimeInterval(-7 * 86400)).timeIntervalSince1970, nil)
        case "month":
            return (cal.startOfDay(for: now.addingTimeInterval(-30 * 86400)).timeIntervalSince1970, nil)
        default:
            return (nil, nil)
        }
    }

    var timeRange: (from: Double?, to: Double?) {
        Store.rangeFor(preset: timePreset, day: selectedDay)
    }

    func reload() {
        let snap = (
            section: section, search: searchText,
            preset: timePreset, day: selectedDay,
            conv: selectedConversationId, asset: selectedAssetId,
            sort: sortMode, tags: selectedTags
        )
        let range = Store.rangeFor(preset: snap.preset, day: snap.day)
        queue.async { [weak self] in
            guard let self, let db = self.db else { return }
            let counts = db.counts()
            let nodes = db.nodes()
            let dups = db.dupGroups()
            var convs: [ConversationRow]?
            var dash: DashboardData?
            var newAssets: [AssetRow]?
            var dashFiles: [AssetRow] = []
            var dashTotal = 0
            var merged: [String: String]?
            var newFacets: [(dim: String, tag: String, count: Int)]?
            var preview = (stale: 0, dedup: 0, ephemeral: 0)
            switch snap.section {
            case .dashboard:
                dash = db.dashboard()
                let f = db.filesFiltered(
                    category: nil, type: nil,
                    protectOnly: false, finalsOnly: false,
                    from: range.from, to: range.to
                )
                dashFiles = f.rows
                dashTotal = f.total
                newAssets = db.assets(section: "library", search: "")
            case .conversations:
                convs = db.conversations()
                if let cid = snap.conv {
                    newAssets = db.conversationFiles(cid)
                } else {
                    newAssets = []
                }
            case .rules:
                var m = [
                    "stale_versions_enabled": "0", "stale_versions_days": "30",
                    "dedup_enabled": "0", "ephemeral_enabled": "0",
                    "quarantine_retention_days": "30",
                ]
                for (k, v) in db.settings() { m[k] = v }
                merged = m
                preview = db.cleanupPreview(
                    staleDays: Int(m["stale_versions_days"] ?? "30") ?? 30
                )
            case .about:
                break
            case .tags:
                newFacets = db.tagFacets()
                if snap.tags.isEmpty {
                    newAssets = []
                } else {
                    let pairs = snap.tags.map { k -> (String, String) in
                        let parts = k.split(separator: "\t", maxSplits: 1)
                        return (String(parts[0]),
                                parts.count > 1 ? String(parts[1]) : "")
                    }
                    newAssets = db.assetsByTags(pairs: pairs)
                }
            case .inbox, .library, .finals, .nodes, .cleanup:
                newAssets = db.assets(
                    section: snap.section.key, search: snap.search,
                    sort: snap.section == .library ? snap.sort : "created"
                )
            }
            var vers: [VersionRow] = []
            var locs: [(node: String, path: String)] = []
            if let aid = snap.asset {
                vers = db.versions(assetId: aid)
                locs = db.locations(assetId: aid)
            }
            DispatchQueue.main.async {
                self.counts = counts
                self.nodes = nodes
                self.dups = dups
                if let convs { self.conversationsList = convs }
                if let dash { self.dash = dash }
                self.dashFiles = dashFiles
                self.dashTotal = dashTotal
                if let newAssets { self.assets = newAssets }
                if let newFacets { self.tagFacets = newFacets }
                if let merged {
                    self.rules = merged
                    self.cleanupPreview = preview
                }
                if snap.asset != nil {
                    self.versions = vers
                    self.locations = locs
                }
            }
        }
    }

    func searchChanged() {
        searchWork?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.reload() }
        searchWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: work)
    }

    // MARK: - Tags & auto-filing

    func toggleTag(_ dim: String, _ tag: String) {
        let k = dim + "\t" + tag
        if selectedTags.contains(k) { selectedTags.remove(k) }
        else { selectedTags.insert(k) }
        reload()
    }

    func clearTags() {
        selectedTags = []
        reload()
    }

    func runTagAll() {
        cli(["tag-all", "--content"]) { [weak self] out in
            self?.organizeResult = out
        }
    }

    private func organizeNodeName() -> String {
        if let n = rules["organize_node"], !n.isEmpty { return n }
        return nodes.first?.name ?? ""
    }

    private func organizeTargetRoot() -> String {
        let raw = rules["organize_root"] ?? ""
        if !raw.isEmpty { return (raw as NSString).expandingTildeInPath }
        return FileManager.default.homeDirectoryForCurrentUser.path
            + "/LeanFile-Library"
    }

    func runOrganizePlan() {
        cli(["organize-plan", organizeNodeName(),
             "--to", organizeTargetRoot()]) { [weak self] out in
            self?.organizeResult = out
        }
    }

    func runOrganizeExecute() {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        cli(["organize-run", organizeNodeName(),
             "--to", organizeTargetRoot(),
             "--manifest", home + "/mm1031-dev/organize-manifest.json",
             "--yes"]) { [weak self] out in
            self?.organizeResult = out
        }
    }

    func select(section newSection: Section) {
        section = newSection
        reload()
    }

    func setSortMode(_ mode: String) {
        guard mode != sortMode else { return }
        sortMode = mode
        reload()
    }

    /// Load rule settings + cleanup preview for the Settings window,
    /// which can be opened without visiting the rules section.
    func refreshRules() {
        queue.async { [weak self] in
            guard let self, let db = self.db else { return }
            var merged = [
                "stale_versions_enabled": "0", "stale_versions_days": "30",
                "dedup_enabled": "0", "ephemeral_enabled": "0",
                "quarantine_retention_days": "30",
            ]
            for (k, v) in db.settings() { merged[k] = v }
            let preview = db.cleanupPreview(
                staleDays: Int(merged["stale_versions_days"] ?? "30") ?? 30)
            DispatchQueue.main.async {
                self.rules = merged
                self.cleanupPreview = preview
            }
        }
    }

    func openDrill(title: String, category: String? = nil, type: String? = nil,
                   protect: Bool = false, finals: Bool = false) {
        drillTitle = title
        // The dashboard List's selection binding resolves selection
        // changes to select(asset:), which closes the drill. Clear the
        // selection and show the drill immediately so no stale selection
        // event from the same tap can kill it afterwards.
        selectedAssetId = nil
        detailShowsDrill = true
        queue.async { [weak self] in
            guard let self, let db = self.db else { return }
            let files = db.filesForDrill(
                category: category, type: type,
                protectOnly: protect, finalsOnly: finals
            )
            DispatchQueue.main.async {
                self.drillFiles = files
                self.detailShowsDrill = true
            }
        }
    }

    func closeDrill() {
        detailShowsDrill = false
        drillTitle = nil
        drillFiles = []
    }

    func openCollectionFile(_ f: CollectionFile) {
        select(asset: AssetRow(
            id: f.id, name: f.name, project: f.project, atype: f.atype,
            state: f.state, inbox: false, latestSeq: 1
        ))
    }

    func select(asset: AssetRow) {
        selectedAssetId = asset.id
        detailShowsDrill = false
        queue.async { [weak self] in
            guard let self, let db = self.db else { return }
            let vers = db.versions(assetId: asset.id)
            let locs = db.locations(assetId: asset.id)
            let prev = db.preview(assetId: asset.id)
            let conv = db.conversation(assetId: asset.id)
            DispatchQueue.main.async {
                self.versions = vers
                self.locations = locs
                self.preview = prev
                self.conversation = conv
            }
        }
    }

    var selectedAsset: AssetRow? {
        assets.first { $0.id == selectedAssetId }
            ?? dashFiles.first { $0.id == selectedAssetId }
    }

    func promoteSelected() {
        guard let sel = selectedAssetId else { return }
        queue.async { [weak self] in
            self?.db?.promote(assetId: sel)
            DispatchQueue.main.async { self?.reload() }
        }
    }

    func selectConversation(_ c: ConversationRow) {
        selectedConversationId = c.id
        reload()
    }

    func setPreset(_ p: String) {
        timePreset = p
        selectedDay = nil
        reload()
    }

    func setDay(_ d: String?) {
        selectedDay = d
        reload()
    }

    func setRule(_ key: String, _ value: String) {
        rules[key] = value
        queue.async { [weak self] in
            self?.db?.setSetting(key, value)
            DispatchQueue.main.async { self?.reload() }
        }
    }

    func runCleanup() {
        cliOpsInFlight += 1
        queue.async { [weak self] in
            guard let self, let db = self.db else { return }
            let home = FileManager.default.homeDirectoryForCurrentUser.path
            let repo = home + "/mm1031-dev"
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            p.arguments = [
                "-m", "mm1031.cli", "--db", db.path, "cleanup-run",
                "--quarantine-dir", repo + "/mm1031-quarantine",
            ]
            p.currentDirectoryURL = URL(fileURLWithPath: repo)
            let pipe = Pipe()
            p.standardOutput = pipe
            p.standardError = pipe
            var result = ""
            do {
                try p.run()
                p.waitUntilExit()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                result = String(data: data, encoding: .utf8) ?? ""
            } catch {
                result = "\(L.t("store.cleanupFailed")): \(error.localizedDescription)"
            }
            DispatchQueue.main.async {
                self.cliOpsInFlight -= 1
                self.cleanupResult = result
                self.reload()
            }
        }
    }

    private func cli(_ args: [String], done: @escaping (String) -> Void) {
        cliOpsInFlight += 1
        queue.async { [weak self] in
            guard let self, let db = self.db else { return }
            let home = FileManager.default.homeDirectoryForCurrentUser.path
            let repo = home + "/mm1031-dev"
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            p.arguments = ["-m", "mm1031.cli", "--db", db.path] + args
            p.currentDirectoryURL = URL(fileURLWithPath: repo)
            let pipe = Pipe()
            p.standardOutput = pipe
            p.standardError = pipe
            var result = ""
            do {
                try p.run()
                p.waitUntilExit()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                result = String(data: data, encoding: .utf8) ?? ""
            } catch {
                result = "\(error.localizedDescription)"
            }
            DispatchQueue.main.async {
                self.cliOpsInFlight -= 1
                done(result)
                self.reload()
            }
        }
    }

    func runBundle(_ convId: String) {
        cli(["bundle", convId]) { [weak self] out in self?.actionMsg = out }
    }

    func runProtect() {
        cli(["protect-run", "--yes"]) { [weak self] out in self?.actionMsg = out }
    }
}

struct ContentView: View {
    @EnvironmentObject var store: Store
    var body: some View {
        Group {
            if store.section == .about || store.section == .rules {
                // Utility pages: two columns, no file inspector.
                NavigationSplitView {
                    SidebarView(badge: badge)
                } detail: {
                    contentColumn
                }
            } else {
                NavigationSplitView {
                    SidebarView(badge: badge)
                } content: {
                    contentColumn
                        .navigationSplitViewColumnWidth(
                            min: 320, ideal: 430, max: 600)
                } detail: {
                    Group {
                        if store.detailShowsDrill {
                            DrillView()
                        } else {
                            inspector
                        }
                    }
                    .navigationSplitViewColumnWidth(
                        min: 280, ideal: 380, max: 560)
                }
            }
        }
        .searchable(text: $store.searchText, prompt: L.t("search.prompt"))
        .onChange(of: store.searchText) { _, _ in store.searchChanged() }
        .onAppear { SelfShot.kick(store: store) }
        .id(store.langTick)
    }

    private func badge(for s: Section) -> Int {
        switch s {
        case .dashboard: return store.counts.total
        case .conversations: return store.counts.convs
        case .inbox: return store.counts.inbox
        case .library: return store.counts.total
        case .tags: return 0
        case .finals: return store.counts.finals
        case .cleanup: return store.counts.dups
        case .nodes: return store.nodes.count
        case .rules: return 0
        case .about: return 0
        }
    }

    private var assetListView: some View {
        List(store.assets, selection: Binding(
            get: { store.selectedAssetId },
            set: { id in
                store.selectedAssetId = id
                if let id, let a = store.assets.first(where: { $0.id == id }) {
                    store.select(asset: a)
                }
            }
        )) { a in
            AssetRowView(asset: a).tag(a.id)
        }
    }

    private var tagDimOrder: [String] {
        ["category", "time", "content", "project", "type", "ext",
         "importance"]
    }

    private func tagChip(dim: String, tag: String, count: Int) -> some View {
        let selected = store.selectedTags.contains(dim + "\t" + tag)
        return Button { store.toggleTag(dim, tag) } label: {
            Text("\(tag) · \(count)")
                .font(.caption).lineLimit(1)
                .padding(.horizontal, 8).padding(.vertical, 4)
                .background(selected ? Color.brandBlue
                                     : Color.gray.opacity(0.15))
                .foregroundStyle(selected ? Color.white : Color.primary)
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
    }

    private var tagsView: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    HStack {
                        Text(L.t("tags.title")).font(.headline)
                        Spacer()
                        if !store.selectedTags.isEmpty {
                            Text(L.f("tags.selected",
                                     store.selectedTags.count))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Button(L.t("tags.clear")) { store.clearTags() }
                                .font(.caption)
                        }
                    }
                    if store.selectedTags.isEmpty {
                        Text(L.t("tags.hint"))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    ForEach(tagDimOrder, id: \.self) { dim in
                        let items = store.tagFacets.filter { $0.dim == dim }
                        if !items.isEmpty {
                            VStack(alignment: .leading, spacing: 5) {
                                Text(L.t("tags.dim." + dim))
                                    .font(.caption2).bold()
                                    .foregroundStyle(.secondary)
                                ScrollView(.horizontal,
                                           showsIndicators: false) {
                                    HStack(spacing: 6) {
                                        ForEach(items, id: \.tag) { it in
                                            tagChip(dim: dim, tag: it.tag,
                                                    count: it.count)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                .padding(10)
            }
            .background(Color(nsColor: .textBackgroundColor))
            .frame(maxHeight: 320)
            Divider()
            if store.selectedTags.isEmpty {
                Spacer()
                Text(L.t("tags.emptyPick"))
                    .foregroundStyle(.secondary)
                Spacer()
            } else {
                assetListView
            }
        }
    }

    @ViewBuilder
    private var contentColumn: some View {
        switch store.section {
        case .dashboard:
            DashboardView()
        case .rules:
            RulesView()
        case .about:
            AboutView()
        case .conversations:
            if let cid = store.selectedConversationId,
               let conv = store.conversationsList.first(where: { $0.id == cid }) {
                VStack(spacing: 0) {
                    HStack(spacing: 10) {
                        Button(L.t("conv.back")) {
                            store.selectedConversationId = nil
                            store.reload()
                        }
                        Text(conv.title).font(.headline).lineLimit(1)
                        Spacer()
                        Text(L.f("conv.produced", conv.files))
                            .font(.caption).foregroundStyle(.secondary)
                        Button(L.t("conv.bundle")) { store.runBundle(conv.id) }
                    }
                    .padding(8)
                    Divider()
                    if !store.actionMsg.isEmpty {
                        Text(store.actionMsg)
                            .font(.caption).foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(8)
                        Divider()
                    }
                    assetListView
                }
            } else {
                List(store.conversationsList) { c in
                    Button {
                        store.selectConversation(c)
                    } label: {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(c.title).font(.headline).lineLimit(1)
                            Text("\(c.tool.isEmpty ? L.t("conv.toolFallback") : c.tool) · \(L.f("conv.files", c.files)) · \(humanBytes(c.bytes))" + (c.inferred ? " · " + L.t("tag.inferred") : " · " + L.t("tag.recorded")))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 2)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .buttonStyle(.plain)
                }
            }
        case .nodes:
            List(store.nodes) { n in
                VStack(alignment: .leading, spacing: 3) {
                    Text(n.name).font(.headline)
                    Text("\(n.kind) · \(L.f("conv.files", n.files)) · \(humanBytes(n.bytes))")
                        .font(.caption).foregroundStyle(.secondary)
                    Text(n.path).font(.caption2).foregroundStyle(.tertiary)
                }
                .padding(.vertical, 2)
            }
        case .cleanup:
            List(store.dups) { d in
                VStack(alignment: .leading, spacing: 3) {
                    Text(d.example).font(.headline)
                    Text(L.f("dup.line", d.copies, humanBytes(d.sizeEach), humanBytes(d.wasted)))
                        .font(.caption).foregroundStyle(.secondary)
                    Text(L.f("dup.hash", String(d.hash.prefix(12))))
                        .font(.caption2).foregroundStyle(.tertiary)
                }
                .padding(.vertical, 2)
            }
        case .tags:
            tagsView
        case .library:
            VStack(spacing: 0) {
                HStack(spacing: 8) {
                    Text(L.t("sort.label"))
                        .font(.caption).foregroundStyle(.secondary)
                    Picker(L.t("sort.label"), selection: Binding(
                        get: { store.sortMode },
                        set: { store.setSortMode($0) }
                    )) {
                        Text(L.t("sort.latest")).tag("latest")
                        Text(L.t("sort.size")).tag("size")
                        Text(L.t("sort.name")).tag("name")
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    Spacer()
                }
                .padding(8)
                Divider()
                assetListView
            }
        default:
            assetListView
        }
    }

    @ViewBuilder
    private var inspector: some View {
        if let a = store.selectedAsset {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if store.drillTitle != nil {
                        Button(L.t("insp.back")) {
                            store.detailShowsDrill = true
                        }
                        .font(.caption)
                    }
                    HStack {
                        Text(a.name).font(.title3).bold()
                        StatePill(state: a.state)
                    }
                    Text("\(a.project) · \(L.typeName(a.atype)) · \(L.f("insp.latestFmt", a.latestSeq))")
                        .font(.caption).foregroundStyle(.secondary)
                    if !store.preview.thumb.isEmpty,
                       let img = NSImage(contentsOfFile: store.preview.thumb) {
                        Image(nsImage: img)
                            .resizable().scaledToFit()
                            .frame(maxHeight: 210)
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                    if !store.preview.excerpt.isEmpty {
                        Text(store.preview.excerpt)
                            .font(.callout).foregroundStyle(.primary)
                            .lineLimit(6)
                            .padding(10)
                            .background(Color.secondary.opacity(0.08))
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                    let conv = store.conversation
                    if !conv.title.isEmpty || !conv.tool.isEmpty {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(L.t("insp.source")).font(.headline)
                            if !conv.title.isEmpty {
                                Text(conv.title + (conv.inferred ? L.t("insp.inferredTag") : ""))
                                    .font(.subheadline)
                            }
                            if !conv.tool.isEmpty {
                                Text(L.f("insp.toolFmt", conv.tool) + (conv.model.isEmpty ? "" : L.f("insp.modelFmt", conv.model)))
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            if !conv.prompt.isEmpty {
                                Text(L.f("insp.promptFmt", conv.prompt))
                                    .font(.caption).foregroundStyle(.secondary).lineLimit(4)
                            }
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.blue.opacity(0.07))
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                    if a.state != "final" && a.state != "published" {
                        Button(L.t("insp.setFinal")) { store.promoteSelected() }
                            .buttonStyle(.borderedProminent)
                    }
                    Divider()
                    Text(L.t("insp.versions")).font(.headline)
                    ForEach(store.versions) { v in
                        VStack(alignment: .leading, spacing: 2) {
                            Text("v\(v.seq) · \(v.shortHash)").font(.subheadline).bold()
                            Text(L.f("insp.authorFmt", v.author) + (v.tool.isEmpty ? "" : L.f("insp.vToolFmt", v.tool)) + (v.model.isEmpty ? "" : L.f("insp.vModelFmt", v.model)))
                                .font(.caption).foregroundStyle(.secondary)
                            if !v.intent.isEmpty {
                                Text(v.intent).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 2)
                    }
                    Divider()
                    Text(L.t("insp.storedIn")).font(.headline)
                    ForEach(Array(store.locations.enumerated()), id: \.offset) { _, loc in
                        VStack(alignment: .leading, spacing: 1) {
                            Text(loc.node).font(.subheadline)
                            Text(loc.path).font(.caption2).foregroundStyle(.tertiary)
                        }
                    }
                    if let first = store.locations.first {
                        Button(L.t("insp.showInFinder")) {
                            NSWorkspace.shared.activateFileViewerSelecting(
                                [URL(fileURLWithPath: first.path)]
                            )
                        }
                    }
                }
                .padding()
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        } else {
            VStack(spacing: 8) {
                Image(systemName: "archivebox").font(.largeTitle).foregroundStyle(.tertiary)
                Text(L.t("insp.empty"))
                    .multilineTextAlignment(.center).foregroundStyle(.secondary)
            }
        }
    }
}

struct AssetRowView: View {
    let asset: AssetRow
    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: icon).font(.title3).frame(width: 26)
            VStack(alignment: .leading, spacing: 2) {
                Text(asset.name).font(.headline).lineLimit(1)
                Text("\(asset.project) · v\(asset.latestSeq)")
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            StatePill(state: asset.state)
        }
        .padding(.vertical, 2)
    }
    private var icon: String {
        switch asset.atype {
        case "document": return "doc.text"
        case "image": return "photo"
        case "video": return "film"
        case "audio": return "waveform"
        case "slides": return "rectangle.on.rectangle"
        default: return "doc"
        }
    }
}

struct StatePill: View {
    let state: String
    var body: some View {
        Text(label)
            .font(.caption2).bold()
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background(color.opacity(0.18))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }
    private var label: String {
        switch state {
        case "draft": return L.t("state.draft")
        case "candidate": return L.t("state.candidate")
        case "final": return L.t("state.final")
        case "published": return L.t("state.published")
        case "archived": return L.t("state.archived")
        default: return state
        }
    }
    private var color: Color {
        switch state {
        case "final": return .orange
        case "candidate": return .blue
        case "published": return .purple
        default: return .gray
        }
    }
}

struct DashboardView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        // NOTE: no selection binding on this List. A selectable List
        // generates selection values from row identities and re-asserts
        // them around content changes; the old binding resolved those
        // to select(asset:), which closed an open drill. File rows below
        // use explicit buttons instead.
        List {
            SwiftUI.Section {
                HStack(spacing: 12) {
                    Image(nsImage: NSApplication.shared.applicationIconImage)
                        .resizable().frame(width: 40, height: 40)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("LeanFile").font(.headline).foregroundStyle(.white)
                        Text(L.t("dash.tagline"))
                            .font(.caption).foregroundStyle(.white.opacity(0.75))
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 2) {
                        Text("\(store.dash.totalFiles)")
                            .font(.title3).bold().foregroundStyle(.white)
                        Text(L.t("card.files"))
                            .font(.caption2).foregroundStyle(Color.brandGold)
                    }
                }
                .padding(12)
                .background(navyGradient)
                .clipShape(RoundedRectangle(cornerRadius: 14))
                .listRowInsets(EdgeInsets(top: 6, leading: 10, bottom: 2, trailing: 10))
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)
            }
            SwiftUI.Section {
                LazyVGrid(
                    columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())],
                    spacing: 10
                ) {
                    Button { store.openDrill(title: L.t("drill.all")) } label: {
                        StatCard(kind: "files", title: L.t("card.files"), value: "\(store.dash.totalFiles)",
                                 sub: L.f("card.filesSub", store.dash.totalCopies))
                    }.buttonStyle(.plain)
                    Button { store.openDrill(title: L.t("drill.all")) } label: {
                        StatCard(kind: "space", title: L.t("card.space"), value: humanBytes(store.dash.totalBytes),
                                 sub: L.t("card.spaceSub"))
                    }.buttonStyle(.plain)
                    Button { store.select(section: .conversations) } label: {
                        StatCard(kind: "conv", title: L.t("card.conv"), value: "\(store.dash.conversations)",
                                 sub: L.t("card.convSub"))
                    }.buttonStyle(.plain)
                    Button { store.openDrill(title: L.t("drill.finals"), finals: true) } label: {
                        StatCard(kind: "finals", title: L.t("card.finals"), value: "\(store.dash.finals)",
                                 sub: L.t("card.finalsSub"))
                    }.buttonStyle(.plain)
                    Button { store.select(section: .cleanup) } label: {
                        StatCard(kind: "reclaim", title: L.t("card.reclaim"), value: humanBytes(store.dash.reclaimable),
                                 sub: L.t("card.reclaimSub"))
                    }.buttonStyle(.plain)
                    Button { store.openDrill(title: L.t("drill.protect"), protect: true) } label: {
                        StatCard(kind: "protect", title: L.t("card.protect"), value: "\(store.dash.protectTotal)",
                                 sub: store.dash.protectAtRisk > 0
                                    ? L.f("card.protectRisk", store.dash.protectAtRisk)
                                    : L.t("card.protectOk"))
                    }.buttonStyle(.plain)
                }
                .padding(.vertical, 4)
            }
            if store.dash.protectAtRisk > 0 {
                SwiftUI.Section {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(L.f("card.protectRisk", store.dash.protectAtRisk))
                                .font(.headline)
                            Text(L.t("ov.protectHint"))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button(L.t("ov.protectNow")) { store.runProtect() }
                    }
                }
            }
            if !store.actionMsg.isEmpty {
                SwiftUI.Section {
                    Text(store.actionMsg)
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            SwiftUI.Section(L.t("dash.byCategory")) {
                ForEach(store.dash.byCategory) { r in
                    Button {
                        store.openDrill(
                            title: L.f("drill.categoryFmt", L.cat(r.label)),
                            category: r.label == "未分类" ? "" : r.label
                        )
                    } label: {
                        breakdownRow(r, display: L.cat(r.label), maxBytes: store.dash.byCategory.map(\.bytes).max() ?? 1)
                    }.buttonStyle(.plain)
                }
            }
            SwiftUI.Section(L.t("dash.byType")) {
                ForEach(store.dash.byType) { r in
                    Button {
                        store.openDrill(title: L.f("drill.typeFmt", L.typeName(r.label)), type: r.label)
                    } label: {
                        breakdownRow(r, display: L.typeName(r.label), maxBytes: store.dash.byType.map(\.bytes).max() ?? 1)
                    }.buttonStyle(.plain)
                }
            }
            SwiftUI.Section(L.t("dash.time")) {
                Picker(L.t("time.range"), selection: Binding(
                    get: { store.timePreset },
                    set: { store.setPreset($0) }
                )) {
                    Text(L.t("range.all")).tag("all")
                    Text(L.t("range.today")).tag("today")
                    Text(L.t("range.week")).tag("week")
                    Text(L.t("range.month")).tag("month")
                }
                .pickerStyle(.segmented)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(store.dash.byDay.prefix(21)) { d in
                            Button {
                                store.setDay(store.selectedDay == d.day ? nil : d.day)
                            } label: {
                                VStack(spacing: 1) {
                                    Text(String(d.day.suffix(5))).font(.caption2).bold()
                                    Text("\(d.files)").font(.caption)
                                }
                                .padding(.horizontal, 7).padding(.vertical, 4)
                                .background(
                                    store.selectedDay == d.day
                                        ? Color.accentColor.opacity(0.25)
                                        : Color.secondary.opacity(0.10)
                                )
                                .clipShape(RoundedRectangle(cornerRadius: 6))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                if let day = store.selectedDay {
                    HStack {
                        Text(L.f("time.viewingDay", day)).font(.caption)
                        Spacer()
                        Button(L.t("time.clear")) { store.setDay(nil) }
                    }
                }
            }
            SwiftUI.Section(L.f("dash.filesFmt", store.dashTotal)) {
                ForEach(store.dashFiles) { a in
                    Button {
                        store.select(asset: a)
                    } label: {
                        AssetRowView(asset: a)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private func breakdownRow(_ r: BreakdownRow, display: String, maxBytes: Int) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(display).font(.subheadline)
                Spacer()
                Text(L.f("breakdown.fmt", r.files, humanBytes(r.bytes)))
                    .font(.caption).foregroundStyle(.secondary)
            }
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 3)
                        .fill(Color.secondary.opacity(0.12))
                        .frame(height: 6)
                    RoundedRectangle(cornerRadius: 3)
                        .fill(brandGradient)
                        .frame(
                            width: max(3, g.size.width * CGFloat(r.bytes) / CGFloat(max(maxBytes, 1))),
                            height: 6
                        )
                }
            }
            .frame(height: 6)
        }
        .padding(.vertical, 1)
    }
}

struct StatCard: View {
    let kind: String
    let title: String
    let value: String
    let sub: String

    private var icon: String {
        switch kind {
        case "files": return "doc.on.doc.fill"
        case "space": return "internaldrive.fill"
        case "conv": return "text.bubble.fill"
        case "finals": return "checkmark.seal.fill"
        case "reclaim": return "trash.fill"
        case "protect": return "shield.fill"
        default: return "doc.fill"
        }
    }
    private var tint: Color {
        switch kind {
        case "files": return .brandBlue
        case "space": return Color(red: 0.35, green: 0.35, blue: 0.90)
        case "conv": return Color(red: 0.05, green: 0.60, blue: 0.60)
        case "finals": return Color(red: 0.13, green: 0.62, blue: 0.33)
        case "reclaim": return Color(red: 0.90, green: 0.50, blue: 0.13)
        case "protect": return Color(red: 0.85, green: 0.30, blue: 0.25)
        default: return .brandBlue
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.caption2).foregroundStyle(.white)
                    .frame(width: 20, height: 20)
                    .background(tint)
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                Text(title).font(.caption2).foregroundStyle(.secondary)
            }
            Text(value).font(.title3).bold().foregroundStyle(Color.brandNavy)
            Text(sub).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(color: .black.opacity(0.07), radius: 5, x: 0, y: 2)
    }
}

struct RulesView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        List {
            SwiftUI.Section(L.t("rules.secStale")) {
                Toggle(L.t("rules.autoStale"),
                       isOn: boolBinding("stale_versions_enabled"))
                Picker(L.t("rules.keepDays"),
                       selection: intBinding("stale_versions_days", 30)) {
                    ForEach([7, 14, 30, 90], id: \.self) { d in
                        Text(L.f("days.fmt", d)).tag(d)
                    }
                }
                Text(L.t("rules.staleNote"))
                    .font(.caption).foregroundStyle(.secondary)
            }
            SwiftUI.Section(L.t("rules.secDup")) {
                Toggle(L.t("rules.autoDup"),
                       isOn: boolBinding("dedup_enabled"))
                Toggle(L.t("rules.autoTemp"),
                       isOn: boolBinding("ephemeral_enabled"))
                Text(L.t("rules.dupNote"))
                    .font(.caption).foregroundStyle(.secondary)
            }
            SwiftUI.Section(L.t("rules.secQuar")) {
                Picker(L.t("rules.retention"),
                       selection: intBinding("quarantine_retention_days", 30)) {
                    ForEach([7, 30, 90], id: \.self) { d in
                        Text(L.f("rules.retentionOpt", d)).tag(d)
                    }
                }
                Text(L.t("rules.quarNote"))
                    .font(.caption).foregroundStyle(.secondary)
            }
            SwiftUI.Section(L.t("rules.secPreview")) {
                LabeledContent(L.t("rules.prevStale"),
                               value: L.f("count.fmt", store.cleanupPreview.stale))
                LabeledContent(L.t("rules.prevDup"),
                               value: L.f("count.fmt", store.cleanupPreview.dedup))
                LabeledContent(L.t("rules.prevTemp"),
                               value: L.f("count.fmt", store.cleanupPreview.ephemeral))
                Button(L.t("rules.run")) { store.runCleanup() }
                    .buttonStyle(.borderedProminent)
                if !store.cleanupResult.isEmpty {
                    Text(store.cleanupResult)
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let last = store.rules["last_cleanup"] {
                    Text(L.f("rules.lastFmt", last))
                        .font(.caption2).foregroundStyle(.tertiary)
                }
            }
            SwiftUI.Section(L.t("organize.title")) {
                Toggle(L.t("organize.auto"),
                       isOn: boolBinding("organize_enabled"))
                Picker(L.t("organize.node"), selection: Binding(
                    get: { store.rules["organize_node"]
                        ?? store.nodes.first?.name ?? "" },
                    set: { store.setRule("organize_node", $0) }
                )) {
                    ForEach(store.nodes, id: \.name) { n in
                        Text(n.name).tag(n.name)
                    }
                }
                TextField(L.t("organize.root"), text: Binding(
                    get: { store.rules["organize_root"]
                        ?? "~/LeanFile-Library" },
                    set: { store.setRule("organize_root", $0) }
                ))
                Text(L.t("organize.note"))
                    .font(.caption).foregroundStyle(.secondary)
                HStack {
                    Button(L.t("organize.plan")) { store.runOrganizePlan() }
                    Button(L.t("organize.run")) {
                        store.runOrganizeExecute()
                    }
                    .buttonStyle(.borderedProminent)
                    Button(L.t("organize.retag")) { store.runTagAll() }
                }
                if !store.organizeResult.isEmpty {
                    Text(store.organizeResult)
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func boolBinding(_ key: String) -> Binding<Bool> {
        Binding(
            get: { store.rules[key] == "1" },
            set: { store.setRule(key, $0 ? "1" : "0") }
        )
    }

    private func intBinding(_ key: String, _ def: Int) -> Binding<Int> {
        Binding(
            get: { Int(store.rules[key] ?? "") ?? def },
            set: { store.setRule(key, String($0)) }
        )
    }
}

private func drillTypeIcon(_ t: String) -> String {
    switch t {
    case "document": return "doc.text"
    case "image": return "photo"
    case "video": return "film"
    case "audio": return "waveform"
    case "slides": return "rectangle.on.rectangle"
    default: return "doc"
    }
}

struct DrillView: View {
    @EnvironmentObject var store: Store
    @State private var mode = "list"

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(store.drillTitle ?? L.t("drill.defaultTitle"))
                        .font(.headline).lineLimit(1)
                    Text(L.f("drill.countFmt", store.drillFiles.count))
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Picker("", selection: $mode) {
                    Text(L.t("drill.list")).tag("list")
                    Text(L.t("drill.grid")).tag("grid")
                }
                .pickerStyle(.segmented)
                .frame(width: 170)
                Button {
                    store.closeDrill()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }
            .padding(10)
            Divider()
            if mode == "list" {
                List(store.drillFiles) { f in
                    Button {
                        store.openCollectionFile(f)
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: drillTypeIcon(f.atype))
                                .frame(width: 24)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(f.title).font(.subheadline).lineLimit(1)
                                Text("\(f.project) · \(humanBytes(f.size))")
                                    .font(.caption2).foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                            Spacer()
                            StatePill(state: f.state)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .buttonStyle(.plain)
                }
            } else {
                ScrollView {
                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 128), spacing: 12)],
                        spacing: 12
                    ) {
                        ForEach(store.drillFiles) { f in
                            Button {
                                store.openCollectionFile(f)
                            } label: {
                                DrillTile(file: f)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(10)
                }
            }
        }
    }
}

struct DrillTile: View {
    let file: CollectionFile

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            ZStack {
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color.secondary.opacity(0.08))
                if !file.thumb.isEmpty,
                   let img = NSImage(contentsOfFile: file.thumb) {
                    Image(nsImage: img)
                        .resizable().scaledToFill()
                } else if !file.excerpt.isEmpty {
                    Text(file.excerpt)
                        .font(.caption2).foregroundStyle(.secondary)
                        .lineLimit(6).padding(7)
                        .frame(maxWidth: .infinity, maxHeight: .infinity,
                               alignment: .topLeading)
                } else {
                    Image(systemName: drillTypeIcon(file.atype))
                        .font(.largeTitle).foregroundStyle(.tertiary)
                }
            }
            .frame(height: 92)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            Text(file.title).font(.caption).lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)
            HStack(spacing: 4) {
                StatePill(state: file.state)
                Text(humanBytes(file.size))
                    .font(.caption2).foregroundStyle(.secondary)
            }
        }
    }
}


// MARK: - About the author

struct AboutView: View {

    private var feedbackURL: URL {
        var c = URLComponents(string: "mailto:sky.kugua@gmail.com")!
        c.queryItems = [
            URLQueryItem(name: "subject", value: "LeanFile 反馈 / Feedback"),
            URLQueryItem(name: "body",
                         value: "我想反馈：\n\n（发生了什么、期望是什么，都可以写）"),
        ]
        return c.url!
    }

    private func avatar() -> NSImage? {
        if let p = Bundle.main.path(forResource: "avatar", ofType: "jpg") {
            return NSImage(contentsOfFile: p)
        }
        return nil
    }

    var body: some View {
        Form {
            SwiftUI.Section {
                HStack(spacing: 16) {
                    Image(nsImage: NSApplication.shared.applicationIconImage)
                        .resizable().frame(width: 56, height: 56)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("LeanFile").font(.title2).bold()
                        Text(L.t("about.app")).foregroundStyle(.secondary)
                    }
                }
            }
            SwiftUI.Section {
                HStack(alignment: .top, spacing: 16) {
                    if let img = avatar() {
                        Image(nsImage: img).resizable()
                            .aspectRatio(contentMode: .fill)
                            .frame(width: 92, height: 92)
                            .clipShape(Circle())
                            .overlay(Circle().stroke(Color(
                                red: 0.79, green: 0.64, blue: 0.15),
                                lineWidth: 2))
                    }
                    VStack(alignment: .leading, spacing: 6) {
                        Text("史凯 Kai Shi").font(.title3).bold()
                            .foregroundStyle(.white)
                        Text(L.t("about.role"))
                            .font(.subheadline)
                            .foregroundStyle(.white.opacity(0.75))
                        Text(L.t("about.bio")).font(.body)
                            .foregroundStyle(.white.opacity(0.92))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(14)
                .background(navyGradient)
                .clipShape(RoundedRectangle(cornerRadius: 14))
            }
            SwiftUI.Section {
                HStack(spacing: 12) {
                    Link(destination: URL(string: "mailto:sky.kugua@gmail.com")!) {
                        Label(L.t("about.email"), systemImage: "envelope")
                    }
                    Link(destination: feedbackURL) {
                        Label(L.t("about.feedback"), systemImage: "text.bubble")
                    }
                    Link(destination: URL(string:
                        "https://github.com/sky791016/LeanFile")!) {
                        Label(L.t("about.star"), systemImage: "star")
                    }
                }
                .buttonStyle(.bordered)
            }
            SwiftUI.Section(L.t("about.sponsor.title")) {
                Text(L.t("about.sponsor.sub")).foregroundStyle(.secondary)
                HStack(spacing: 12) {
                    Link(destination: URL(string:
                        "https://sky791016.github.io/LeanFile/#sponsor")!) {
                        Label(L.t("about.sponsor.usd"), systemImage: "heart")
                    }
                    .buttonStyle(.borderedProminent)
                    Link(destination: URL(string:
                        "https://sky791016.github.io/LeanFile/#sponsor")!) {
                        Label(L.t("about.sponsor.cny"), systemImage: "gift")
                    }
                    .buttonStyle(.borderedProminent)
                }
                Link(L.t("about.sponsor.more"), destination: URL(string:
                    "https://sky791016.github.io/LeanFile/#sponsor")!)
            }
        }
        .formStyle(.grouped)
    }
}

// MARK: - Sidebar (brand) + ad card

struct AdEntry: Codable, Identifiable {
    var id: String
    var icon: String
    var tint: String
    var titleZh: String
    var titleEn: String
    var textZh: String
    var textEn: String
    var url: String
    var title: String { L.isZh ? titleZh : titleEn }
    var text: String { L.isZh ? textZh : textEn }
    var tintColor: Color {
        switch tint {
        case "gold": return .brandGold
        case "cyan": return .brandCyan
        case "green": return Color(red: 0.15, green: 0.65, blue: 0.35)
        default: return .brandBlue
        }
    }
}

enum AdService {
    static let defaults: [AdEntry] = [
        AdEntry(id: "book", icon: "book.closed.fill", tint: "blue",
                titleZh: "《精益数据方法论》", titleEn: "Lean Data Discovery",
                textZh: "英文版由 Springer Nature 全球出版——数据驱动的数字化转型方法论。",
                textEn: "The Lean Data Methodology, published worldwide by Springer Nature.",
                url: "https://leanvalue.online"),
        AdEntry(id: "course", icon: "graduationcap.fill", tint: "cyan",
                titleZh: "凯哥讲 AI · LeanFDE", titleEn: "Kai Talks AI · LeanFDE",
                textZh: "从 AI Native 到 Value Native：FDE 落地方法与课程。",
                textEn: "From AI Native to Value Native — the FDE playbook and courses.",
                url: "https://leanvalue.online"),
        AdEntry(id: "cloud", icon: "cloud.fill", tint: "gold",
                titleZh: "LeanFile 官方云", titleEn: "LeanFile Cloud",
                textZh: "同步、备份、团队协作——增值云服务即将上线，敬请期待。",
                textEn: "Sync, backup and team collaboration — the official cloud is coming soon.",
                url: "https://sky791016.github.io/LeanFile/#cloud"),
        AdEntry(id: "sponsor", icon: "megaphone.fill", tint: "green",
                titleZh: "赞助位招租", titleEn: "Your product here",
                textZh: "这个位置也可以是你的产品——赞助 LeanFile，触达 AI 文件管理用户。",
                textEn: "This slot can carry your product — sponsor LeanFile and reach AI-era file users.",
                url: "https://sky791016.github.io/LeanFile/#advertise"),
    ]

    static func fetchRemote(_ done: @escaping ([AdEntry]) -> Void) {
        guard let u = URL(string: "https://sky791016.github.io/LeanFile/ads.json")
        else { return }
        URLSession.shared.dataTask(with: u) { data, _, _ in
            guard let data,
                  let list = try? JSONDecoder().decode([AdEntry].self, from: data),
                  !list.isEmpty else { return }
            DispatchQueue.main.async { done(list) }
        }.resume()
    }
}

struct AdCard: View {
    @State private var entries: [AdEntry] = AdService.defaults
    @State private var idx = 0
    @State private var hidden = false
    private let timer = Timer.publish(every: 18, on: .main, in: .common)
        .autoconnect()

    var body: some View {
        if !hidden && !entries.isEmpty {
            let ad = entries[idx % entries.count]
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(L.isZh ? "广告" : "AD")
                        .font(.caption2).bold().foregroundStyle(Color.brandGold)
                    Spacer()
                    Button { hidden = true } label: {
                        Image(systemName: "xmark").font(.caption2)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.white.opacity(0.5))
                }
                Button {
                    if let u = URL(string: ad.url) {
                        NSWorkspace.shared.open(u)
                    }
                } label: {
                    VStack(alignment: .leading, spacing: 5) {
                        HStack(spacing: 7) {
                            Image(systemName: ad.icon)
                                .font(.subheadline).foregroundStyle(.white)
                                .frame(width: 24, height: 24)
                                .background(ad.tintColor)
                                .clipShape(RoundedRectangle(cornerRadius: 7))
                            Text(ad.title)
                                .font(.subheadline).bold()
                                .foregroundStyle(.white).lineLimit(1)
                        }
                        Text(ad.text)
                            .font(.caption)
                            .foregroundStyle(.white.opacity(0.78))
                            .lineLimit(3)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .buttonStyle(.plain)
            }
            .padding(11)
            .background(Color.white.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(Color.white.opacity(0.12), lineWidth: 1)
            )
            .onReceive(timer) { _ in idx = (idx + 1) % entries.count }
            .onAppear { AdService.fetchRemote { entries = $0 } }
        }
    }
}

struct SidebarView: View {
    @EnvironmentObject var store: Store
    let badge: (Section) -> Int
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(nsImage: NSApplication.shared.applicationIconImage)
                    .resizable().frame(width: 30, height: 30)
                VStack(alignment: .leading, spacing: 1) {
                    Text("LeanFile").font(.headline).foregroundStyle(.white)
                    Text("MM1031")
                        .font(.caption2).foregroundStyle(Color.brandGold)
                }
                Spacer()
            }
            .padding(.horizontal, 14)
            .padding(.top, 14)
            .padding(.bottom, 10)

            VStack(spacing: 2) {
                ForEach(Section.allCases.filter { $0 != .rules }) { s in
                    Button { store.select(section: s) } label: {
                        HStack(spacing: 9) {
                            Image(systemName: s.icon).frame(width: 18)
                            Text(s.title).font(.subheadline).lineLimit(1)
                            Spacer()
                            if badge(s) > 0 {
                                Text("\(badge(s))")
                                    .font(.caption2).bold()
                                    .padding(.horizontal, 6)
                                    .padding(.vertical, 2)
                                    .background(Color.white.opacity(0.16))
                                    .clipShape(Capsule())
                            }
                        }
                        .foregroundStyle(
                            store.section == s ? .white : .white.opacity(0.72))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)
                        .background(
                            store.section == s
                                ? Color.white.opacity(0.13) : Color.clear)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .overlay(alignment: .leading) {
                            if store.section == s {
                                RoundedRectangle(cornerRadius: 2)
                                    .fill(Color.brandGold)
                                    .frame(width: 3, height: 18)
                                    .offset(x: -6)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 10)

            Spacer()
            // PERMANENT settings entry: hard-wired into the sidebar.
            // No setting may hide it — if it could disappear, the user
            // would have no way back into Settings.
            Button { openSettings() } label: {
                HStack(spacing: 9) {
                    Image(systemName: "gearshape").frame(width: 18)
                    Text(L.t("settings.title")).font(.subheadline)
                    Spacer()
                    Text("⌘,")
                        .font(.caption2)
                        .foregroundStyle(.white.opacity(0.45))
                }
                .foregroundStyle(.white.opacity(0.88))
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 10)
            AdCard().padding(.horizontal, 10)
            Text("v0.1.0")
                .font(.caption2)
                .foregroundStyle(.white.opacity(0.4))
                .padding(.vertical, 8)
        }
        .background(navyGradient)
        .navigationSplitViewColumnWidth(min: 200, ideal: 220)
    }
}

// MARK: - Settings window

struct SettingsView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        TabView {
            GeneralSettingsView()
                .tabItem {
                    Label(L.t("settings.general"), systemImage: "gearshape")
                }
            RulesView()
                .tabItem {
                    Label(L.t("section.rules"),
                          systemImage: "slider.horizontal.3")
                }
        }
        .frame(width: 580, height: 500)
        .onAppear { store.refreshRules() }
    }
}

struct GeneralSettingsView: View {
    @EnvironmentObject var store: Store
    @AppStorage("mm1031.lang") private var langPref = ""

    var body: some View {
        Form {
            SwiftUI.Section("语言 Language") {
                Picker("语言 Language", selection: $langPref) {
                    Text("跟随系统 System").tag("")
                    Text("中文").tag("zh")
                    Text("English").tag("en")
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .onChange(of: langPref) { _, _ in store.langTick += 1 }
            }
            SwiftUI.Section {
                LabeledContent("LeanFile", value: "v0.1.0 · MM1031")
            }
        }
        .formStyle(.grouped)
    }
}

// MARK: - Self-shot mode (LEANFILE_SHOTS=<dir>): renders the app's own
// window to PNGs for documentation/QA, independent of screen lock state.
private enum SelfShot {
    static func kick(store: Store) {
        guard let dir = ProcessInfo.processInfo.environment["LEANFILE_SHOTS"],
              !dir.isEmpty else { return }
        Task { @MainActor in await run(store: store, dir: dir) }
    }

    @MainActor
    private static func run(store: Store, dir: String) async {
        try? FileManager.default.createDirectory(
            atPath: dir, withIntermediateDirectories: true)
        if let win = NSApp.windows.first(where: { $0.contentView != nil }) {
            win.setFrame(NSRect(x: 60, y: 60, width: 1500, height: 940),
                         display: true)
        }
        func snap(_ name: String) {
            guard let win = NSApp.windows.first(where: { $0.contentView != nil }),
                  let view = win.contentView,
                  let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds)
            else { return }
            view.cacheDisplay(in: view.bounds, to: rep)
            if let data = rep.representation(using: .png, properties: [:]) {
                try? data.write(to: URL(fileURLWithPath: dir + "/" + name))
            }
        }
        func wait(_ s: Double) async {
            try? await Task.sleep(nanoseconds: UInt64(s * 1_000_000_000))
        }
        await wait(2.2); snap("shot-dashboard.png")
        store.openDrill(title: L.f("drill.categoryFmt", L.cat("表格数据")),
                        category: "表格数据")
        await wait(1.8); snap("shot-drill.png")
        store.closeDrill()
        store.select(section: .conversations)
        await wait(1.5); snap("shot-conversations.png")
        if let c = store.conversationsList.first {
            store.selectConversation(c)
        }
        await wait(1.5); snap("shot-conversation.png")
        store.select(section: .about)
        await wait(1.5); snap("shot-about.png")
        store.select(section: .rules)
        await wait(1.5); snap("shot-rules.png")
        store.select(section: .tags)
        await wait(1.5); snap("shot-tags.png")
        if let first = store.tagFacets.first(where: { $0.dim == "category" }) {
            store.toggleTag("category", first.tag)
        }
        await wait(1.5); snap("shot-tags-filtered.png")
        let mainWin = NSApp.windows.first(where: { $0.contentView != nil })
        NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
        await wait(1.4)
        if let sw = NSApp.windows.first(where: {
               $0 != mainWin && $0.contentView != nil
               && $0.frame.width > 400 && $0.frame.width < 900 }),
           let view = sw.contentView,
           let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) {
            view.cacheDisplay(in: view.bounds, to: rep)
            if let data = rep.representation(using: .png, properties: [:]) {
                try? data.write(to: URL(fileURLWithPath: dir + "/shot-settings.png"))
            }
        }
        store.select(section: .dashboard)
    }
}
