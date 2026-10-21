import SwiftUI
import AppKit

@main
struct GuicangApp: App {
    @StateObject private var store = Store()

    var body: some Scene {
        WindowGroup("LeanFile") {
            ContentView()
                .environmentObject(store)
                .frame(minWidth: 980, minHeight: 600)
        }
        .windowStyle(.titleBar)

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
    case finals = "finals"
    case nodes = "nodes"
    case cleanup = "cleanup"
    case rules = "rules"
    var id: String { rawValue }
    var title: String { L.t("section." + key) }
    var key: String {
        switch self {
        case .dashboard: return "dashboard"
        case .conversations: return "conversations"
        case .inbox: return "inbox"
        case .library: return "library"
        case .finals: return "finals"
        case .nodes: return "nodes"
        case .cleanup: return "cleanup"
        case .rules: return "rules"
        }
    }
    var icon: String {
        switch self {
        case .dashboard: return "square.grid.2x2"
        case .conversations: return "text.bubble"
        case .inbox: return "tray.full"
        case .library: return "books.vertical"
        case .finals: return "checkmark.seal"
        case .nodes: return "externaldrive.connected.to.line.below"
        case .cleanup: return "trash"
        case .rules: return "slider.horizontal.3"
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
    @Published var nodes: [NodeRow] = []
    @Published var dups: [DupRow] = []
    @Published var conversationsList: [ConversationRow] = []
    @Published var selectedConversationId: String?
    @Published var counts = (inbox: 0, total: 0, finals: 0, dups: 0, convs: 0)
    @Published var selectedAssetId: String?
    @Published var versions: [VersionRow] = []
    @Published var locations: [(node: String, path: String)] = []
    @Published var preview = (thumb: "", excerpt: "", title: "")
    @Published var conversation = (tool: "", model: "", title: "", inferred: false, prompt: "")
    @Published var searchText: String = ""

    private var db: Database?
    // All database work runs on this serial queue, never on the main
    // thread: the UI must never freeze waiting for SQLite.
    private let queue = DispatchQueue(label: "tech.guicang.store", qos: .userInitiated)
    private var searchWork: DispatchWorkItem?

    init() {
        let env = ProcessInfo.processInfo.environment["GUICANG_DB"]
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let path = env ?? (home + "/guicang-dev/ky-live.db")
        db = Database(path: path)
        reload()
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
            conv: selectedConversationId, asset: selectedAssetId
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
            case .inbox, .library, .finals, .nodes, .cleanup:
                newAssets = db.assets(section: snap.section.key, search: snap.search)
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

    func select(section newSection: Section) {
        section = newSection
        reload()
    }

    func openDrill(title: String, category: String? = nil, type: String? = nil,
                   protect: Bool = false, finals: Bool = false) {
        drillTitle = title
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
        queue.async { [weak self] in
            guard let self, let db = self.db else { return }
            let home = FileManager.default.homeDirectoryForCurrentUser.path
            let repo = home + "/guicang-dev"
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
            p.arguments = [
                "-m", "guicang.cli", "--db", db.path, "cleanup-run",
                "--quarantine-dir", repo + "/guicang-quarantine",
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
                self.cleanupResult = result
                self.reload()
            }
        }
    }
}

struct ContentView: View {
    @EnvironmentObject var store: Store

    var body: some View {
        NavigationSplitView {
            List(Section.allCases, selection: Binding(
                get: { store.section },
                set: { if let s = $0 { store.select(section: s) } }
            )) { s in
                Label(s.title, systemImage: s.icon)
                    .badge(badge(for: s))
                    .tag(s)
            }
            .navigationSplitViewColumnWidth(min: 170, ideal: 190)
        } content: {
            contentColumn
        } detail: {
            if store.detailShowsDrill {
                DrillView()
            } else {
                inspector
            }
        }
        .searchable(text: $store.searchText, prompt: L.t("search.prompt"))
        .onChange(of: store.searchText) { _, _ in store.searchChanged() }
    }

    private func badge(for s: Section) -> Int {
        switch s {
        case .dashboard: return store.counts.total
        case .conversations: return store.counts.convs
        case .inbox: return store.counts.inbox
        case .library: return store.counts.total
        case .finals: return store.counts.finals
        case .cleanup: return store.counts.dups
        case .nodes: return store.nodes.count
        case .rules: return 0
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

    @ViewBuilder
    private var contentColumn: some View {
        switch store.section {
        case .dashboard:
            DashboardView()
        case .rules:
            RulesView()
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
                    }
                    .padding(8)
                    Divider()
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
        List(selection: Binding(
            get: { store.selectedAssetId },
            set: { id in
                store.selectedAssetId = id
                if let id, let a = (store.assets + store.dashFiles).first(where: { $0.id == id }) {
                    store.select(asset: a)
                }
            }
        )) {
            SwiftUI.Section {
                LazyVGrid(
                    columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())],
                    spacing: 10
                ) {
                    Button { store.openDrill(title: L.t("drill.all")) } label: {
                        StatCard(title: L.t("card.files"), value: "\(store.dash.totalFiles)",
                                 sub: L.f("card.filesSub", store.dash.totalCopies))
                    }.buttonStyle(.plain)
                    Button { store.openDrill(title: L.t("drill.all")) } label: {
                        StatCard(title: L.t("card.space"), value: humanBytes(store.dash.totalBytes),
                                 sub: L.t("card.spaceSub"))
                    }.buttonStyle(.plain)
                    Button { store.select(section: .conversations) } label: {
                        StatCard(title: L.t("card.conv"), value: "\(store.dash.conversations)",
                                 sub: L.t("card.convSub"))
                    }.buttonStyle(.plain)
                    Button { store.openDrill(title: L.t("drill.finals"), finals: true) } label: {
                        StatCard(title: L.t("card.finals"), value: "\(store.dash.finals)",
                                 sub: L.t("card.finalsSub"))
                    }.buttonStyle(.plain)
                    Button { store.select(section: .cleanup) } label: {
                        StatCard(title: L.t("card.reclaim"), value: humanBytes(store.dash.reclaimable),
                                 sub: L.t("card.reclaimSub"))
                    }.buttonStyle(.plain)
                    Button { store.openDrill(title: L.t("drill.protect"), protect: true) } label: {
                        StatCard(title: L.t("card.protect"), value: "\(store.dash.protectTotal)",
                                 sub: store.dash.protectAtRisk > 0
                                    ? L.f("card.protectRisk", store.dash.protectAtRisk)
                                    : L.t("card.protectOk"))
                    }.buttonStyle(.plain)
                }
                .padding(.vertical, 4)
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
                    AssetRowView(asset: a).tag(a.id)
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
                RoundedRectangle(cornerRadius: 3)
                    .fill(Color.accentColor.opacity(0.55))
                    .frame(
                        width: max(3, g.size.width * CGFloat(r.bytes) / CGFloat(max(maxBytes, 1))),
                        height: 5
                    )
            }
            .frame(height: 5)
        }
        .padding(.vertical, 1)
    }
}

struct StatCard: View {
    let title: String
    let value: String
    let sub: String
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.caption2).foregroundStyle(.secondary)
            Text(value).font(.title3).bold()
            Text(sub).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(9)
        .background(Color.secondary.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 9))
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
